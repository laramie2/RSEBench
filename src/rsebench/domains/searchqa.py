"""Grounded SearchQA evidence noise with answer-safety hard gates."""
from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field

from rsebench.contracts import TaskManifest, ValidationReport
from rsebench.providers.deepseek import DeepSeekClient

MAX_CONTEXT_CHARS = 6000
TEMPLATE_VERSION = "searchqa-semantic-decoy-v2-gold-exclusion"
_BUDGETS = {"L1": 1, "L2": 2, "L3": 3}
_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


class SearchQADecoyCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decoy_passages: list[str] = Field(min_length=1, max_length=3)


class SearchQANoiseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    noisy_context: str
    noisy_hash: str
    validation: ValidationReport


def _normalize(value: str) -> str:
    tokens = re.sub(r"[^\w]+", " ", value.casefold()).split()
    return " ".join(_NUMBER_WORDS.get(token, token) for token in tokens)


def _truncate_context(context: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    if len(context) <= max_chars:
        return context
    documents = context.split("[DOC]")
    result = ""
    for document in documents:
        candidate = result + "[DOC]" + document if result else document
        if len(candidate) > max_chars:
            break
        result = candidate
    return result or context[:max_chars]


def generate_semantic_decoy_evidence(
    task: TaskManifest,
    *,
    client: DeepSeekClient,
    severity: str,
    seed: int,
) -> SearchQADecoyCandidate:
    budget = _BUDGETS.get(severity)
    if budget is None:
        raise ValueError(f"unsupported severity: {severity}")
    prompt = (
        "为检索问答鲁棒性评测生成语义相关、但结论错误的证据片段。"
        "每个片段必须像搜索结果摘要，明确断言一个具体且貌似合理的错误答案；"
        "不得表达犹豫，不得说明它是干扰项。下面给出的金标准答案仅用于排除："
        "片段中的断言必须与它不同，并且不得出现或改写它。"
        f"只返回 JSON：{{\"decoy_passages\": [字符串]}}，数组必须恰好有 {budget} 项。\n"
        f"问题: {task.prompt}\n排除答案: {task.gold_answers}\n"
        f"强度: {severity}\n随机种子: {seed}"
    )
    cache_payload = (
        f"{task.source_hash}:{TEMPLATE_VERSION}:{severity}:{seed}"
    )
    response = client.complete(
        [{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        cache_key=hashlib.sha256(cache_payload.encode("utf-8")).hexdigest(),
        role="noise_generator",
    )
    try:
        candidate = SearchQADecoyCandidate.model_validate_json(response.content)
    except Exception as exc:
        raise ValueError("invalid SearchQA evidence-noise JSON") from exc
    if len(candidate.decoy_passages) != budget:
        raise ValueError(
            f"SearchQA evidence-noise budget mismatch: {len(candidate.decoy_passages)} != {budget}"
        )
    return candidate


def inject_semantic_decoy_evidence(
    task: TaskManifest,
    candidate: SearchQADecoyCandidate,
    *,
    severity: str,
    seed: int,
) -> SearchQANoiseResult:
    budget = _BUDGETS.get(severity)
    if budget is None:
        raise ValueError(f"unsupported severity: {severity}")
    original_context = str(task.metadata.get("context") or "").strip()
    passages = [passage.strip() for passage in candidate.decoy_passages]
    decoy_context = "\n".join(f"[DOC] {passage}" for passage in passages)
    noisy_context = f"{decoy_context}\n{original_context}" if decoy_context else original_context
    structural = (
        bool(original_context)
        and original_context in noisy_context
        and len(passages) == budget
        and all(passages)
    )
    normalized_decoys = _normalize(decoy_context)
    leak_free = all(
        not _normalize(answer) or _normalize(answer) not in normalized_decoys
        for answer in task.gold_answers
    )
    visible_context = _normalize(_truncate_context(noisy_context))
    answer_visible = any(
        _normalize(answer) and _normalize(answer) in visible_context
        for answer in task.gold_answers
    )
    accepted = structural and leak_free and answer_visible
    validation = ValidationReport(
        structural_valid=structural,
        label_invariant=original_context in noisy_context,
        solvable=answer_visible,
        answer_leak_free=leak_free,
        accepted=accepted,
        checks={
            "decoy_count": len(passages),
            "answer_visible_after_truncation": answer_visible,
            "max_context_chars": MAX_CONTEXT_CHARS,
        },
        messages=[] if accepted else ["SearchQA evidence hard gate failed"],
    )
    payload = {
        "task_id": task.task_id,
        "severity": severity,
        "seed": seed,
        "template_version": TEMPLATE_VERSION,
        "noisy_context": noisy_context,
    }
    noisy_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return SearchQANoiseResult(
        noisy_context=noisy_context,
        noisy_hash=noisy_hash,
        validation=validation,
    )
