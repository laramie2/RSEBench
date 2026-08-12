"""Math reasoning noise generated and screened by independent critics."""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict

from rsebench.contracts import ValidationReport
from rsebench.prompts.math_noise import (
    CRITIC_ERROR_PROMPT,
    CRITIC_VALIDITY_PROMPT,
    GENERATOR_PROMPT,
    GENERATOR_TEMPLATE_VERSION,
)
from rsebench.providers.deepseek import DeepSeekClient


class MathNoiseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partial_solution: str
    error_step: str
    error_type: str
    incorrect_conclusion: str
    critic_error_present: bool = False
    critic_error_type: str = ""
    critic_valid_proof: bool = True
    attempt_index: int = 0

    @property
    def full_text(self) -> str:
        return f"{self.partial_solution}\n{self.incorrect_conclusion}"


class CandidateGenerationError(RuntimeError):
    pass


def _compact_math(text: str) -> str:
    text = text.casefold().replace(",", "")
    text = re.sub(r"\\(?:boxed|fbox)\s*\{([^{}]+)\}", r"\1", text)
    return re.sub(r"\s+", "", text)


def scan_answer_leak(text: str, gold_answer: str) -> bool:
    gold = _compact_math(str(gold_answer).strip().strip("$"))
    if not gold:
        return False
    compact = _compact_math(text)
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", gold):
        literals = re.findall(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", compact)
        return gold.lstrip("+") in {literal.lstrip("+") for literal in literals}
    return gold in compact


def wrap_failed_attempt(problem: str, attempt: str) -> str:
    return (
        "[可能有误的失败尝试：仅作干扰信息，不得视为权威解答]\n"
        f"{attempt}\n"
        "[/失败尝试]\n\n"
        "[原始数学问题]\n"
        f"{problem}"
    )


def _same_error_type(expected: str, observed: str) -> bool:
    first = re.sub(r"[^a-z0-9]+", "", expected.casefold())
    second = re.sub(r"[^a-z0-9]+", "", observed.casefold())
    return bool(first and second and (first in second or second in first))


def validate_flawed_solution(
    candidate: MathNoiseCandidate, gold_answer: str
) -> ValidationReport:
    structural = all(
        value.strip()
        for value in (
            candidate.partial_solution,
            candidate.error_step,
            candidate.error_type,
            candidate.incorrect_conclusion,
        )
    )
    localized_error = candidate.critic_error_present and _same_error_type(
        candidate.error_type, candidate.critic_error_type
    )
    leak_free = not scan_answer_leak(candidate.full_text, gold_answer)
    invalid_proof = not candidate.critic_valid_proof
    accepted = structural and localized_error and leak_free and invalid_proof
    messages: list[str] = []
    if not localized_error:
        messages.append("critic could not confirm the declared error")
    if not leak_free:
        messages.append("candidate leaks the gold answer")
    if not invalid_proof:
        messages.append("independent critic judged the attempt valid")
    return ValidationReport(
        structural_valid=structural,
        label_invariant=True,
        solvable=True,
        answer_leak_free=leak_free,
        accepted=accepted,
        checks={
            "critic_error_present": candidate.critic_error_present,
            "critic_valid_proof": candidate.critic_valid_proof,
            "error_type_agreement": localized_error,
        },
        messages=messages,
    )


def _json_response(
    client: DeepSeekClient, prompt: str, cache_key: str
) -> dict:
    response = client.complete(
        [{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        cache_key=cache_key,
    )
    try:
        payload = json.loads(response.content)
    except json.JSONDecodeError as exc:
        raise ValueError("DeepSeek returned invalid JSON for math noise") from exc
    if not isinstance(payload, dict):
        raise ValueError("DeepSeek math-noise response must be a JSON object")
    return payload


def _cache_key(task_hash: str, stage: str, severity: str, seed: int, attempt: int) -> str:
    raw = (
        f"{task_hash}:{GENERATOR_TEMPLATE_VERSION}:{stage}:{severity}:{seed}:{attempt}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_flawed_solution(
    *,
    problem: str,
    gold_answer: str,
    task_hash: str,
    client: DeepSeekClient,
    severity: str,
    seed: int,
    max_attempts: int = 3,
) -> MathNoiseCandidate:
    required = {
        "partial_solution",
        "error_step",
        "error_type",
        "incorrect_conclusion",
    }
    rejected: list[str] = []
    for attempt in range(max_attempts):
        generated = _json_response(
            client,
            GENERATOR_PROMPT.format(problem=problem, severity=severity, seed=seed + attempt),
            _cache_key(task_hash, "generator", severity, seed, attempt),
        )
        if not required <= generated.keys() or not all(
            isinstance(generated[name], str) for name in required
        ):
            rejected.append("generator_schema")
            continue
        attempt_text = (
            f"{generated['partial_solution']}\n{generated['incorrect_conclusion']}"
        )
        if scan_answer_leak(attempt_text, gold_answer):
            rejected.append("answer_leak")
            continue
        critic_error = _json_response(
            client,
            CRITIC_ERROR_PROMPT.format(problem=problem, attempt=attempt_text),
            _cache_key(task_hash, "critic-error", severity, seed, attempt),
        )
        critic_validity = _json_response(
            client,
            CRITIC_VALIDITY_PROMPT.format(problem=problem, attempt=attempt_text),
            _cache_key(task_hash, "critic-validity", severity, seed, attempt),
        )
        candidate = MathNoiseCandidate(
            **{name: generated[name] for name in required},
            critic_error_present=bool(critic_error.get("error_present", False)),
            critic_error_type=str(critic_error.get("error_type", "")),
            critic_valid_proof=bool(critic_validity.get("valid_proof", True)),
            attempt_index=attempt,
        )
        report = validate_flawed_solution(candidate, gold_answer)
        if report.accepted:
            return candidate
        rejected.append(",".join(report.messages) or "critic_gate")
    raise CandidateGenerationError(
        f"no valid flawed solution after {max_attempts} attempts: {rejected}"
    )
