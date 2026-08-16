"""Normalize native SkillFlow/Harbor evidence without hiding failed outcomes."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Literal, Mapping

from pydantic import Field, model_validator

from rsebench.skillflow.contracts import FrozenStrictModel, SkillFlowFamilyManifest
from rsebench.usage.ledger import aggregate_token_usage


ArmName = Literal["base", "clean_evolution"]
ReplicateId = Literal["r1", "r2", "r3"]

_SKILL_PATH_PATTERN = re.compile(
    r"(?:/|^)(?:\.claude/skills|\.codex/skills|\.agents/skills|skills)/"
    r"([^/\\\"'\s]+)(?:/SKILL\.md|/|$)"
)
_SHELL_READ_PATTERN = re.compile(
    r"(?:^|[;&|]\s*|\b)(?:cat|sed|awk|grep|head|tail|less|more)\b",
    re.IGNORECASE,
)


class SkillFlowTokenUsage(FrozenStrictModel):
    attempted_calls: int = Field(ge=0)
    observed_calls: int = Field(ge=0)
    observed_coverage: float = Field(ge=0.0, le=1.0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class SkillFlowTaskResult(FrozenStrictModel):
    task_id: str = Field(min_length=1)
    order: int = Field(ge=1)
    reward: float
    task_checksum: str = Field(min_length=1)
    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(ge=0.0)
    agent_duration_seconds: float = Field(ge=0.0)
    verifier_duration_seconds: float = Field(ge=0.0)
    patch_duration_seconds: float | None = Field(default=None, ge=0.0)
    skill_use_calls: int = Field(ge=0)
    skills_used: list[str]
    exception_type: str | None

    @model_validator(mode="after")
    def validate_timing_and_usage(self) -> "SkillFlowTaskResult":
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("SkillFlow task timestamps must include a timezone")
        if self.finished_at < self.started_at:
            raise ValueError("SkillFlow task finished before it started")
        if len(self.skills_used) != len(set(self.skills_used)):
            raise ValueError("SkillFlow skills_used must be unique")
        return self


class SkillFlowArmResult(FrozenStrictModel):
    family: str = Field(min_length=1)
    replicate_id: ReplicateId
    arm: ArmName
    complete: bool
    invalid_reasons: list[str]
    task_results: list[SkillFlowTaskResult]
    task_rewards: list[float]
    patch_count: int = Field(ge=0)
    nonempty_patch_count: int = Field(ge=0)
    skill_used_task_count: int = Field(ge=0)
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None = Field(default=None, ge=0.0)
    token_usage: SkillFlowTokenUsage

    @model_validator(mode="after")
    def validate_arm(self) -> "SkillFlowArmResult":
        if self.complete == bool(self.invalid_reasons):
            raise ValueError("complete arm status must agree with invalid_reasons")
        if self.task_rewards != [task.reward for task in self.task_results]:
            raise ValueError("task_rewards must preserve task_results order")
        if self.nonempty_patch_count > self.patch_count:
            raise ValueError("nonempty patch count cannot exceed patch count")
        if self.skill_used_task_count > len(self.task_results):
            raise ValueError("skill-used task count exceeds task count")
        if (self.started_at is None) != (self.finished_at is None):
            raise ValueError("arm timing requires both start and finish")
        if self.started_at is not None and self.finished_at is not None:
            if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
                raise ValueError("SkillFlow arm timestamps must include a timezone")
            if self.finished_at < self.started_at:
                raise ValueError("SkillFlow arm finished before it started")
        return self


class SkillFlowReplicateResult(FrozenStrictModel):
    family: str = Field(min_length=1)
    replicate_id: ReplicateId
    complete: bool
    invalid_reasons: list[str]
    base: SkillFlowArmResult
    evolution: SkillFlowArmResult
    delta_late: float | None
    delta_full: float | None

    @model_validator(mode="after")
    def validate_pair(self) -> "SkillFlowReplicateResult":
        if self.complete == bool(self.invalid_reasons):
            raise ValueError("complete pair status must agree with invalid_reasons")
        if self.base.arm != "base" or self.evolution.arm != "clean_evolution":
            raise ValueError("replicate pair requires base and clean_evolution arms")
        if any(
            item.family != self.family or item.replicate_id != self.replicate_id
            for item in (self.base, self.evolution)
        ):
            raise ValueError("replicate identity differs from arm identity")
        if self.complete and (self.delta_late is None or self.delta_full is None):
            raise ValueError("complete pair requires both deltas")
        if not self.complete and (self.delta_late is not None or self.delta_full is not None):
            raise ValueError("invalid pair cannot report efficacy deltas")
        return self


def _invalid_token_usage() -> SkillFlowTokenUsage:
    return SkillFlowTokenUsage(
        attempted_calls=0,
        observed_calls=0,
        observed_coverage=0.0,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
    )


def _parse_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_timestamp:{label}")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid_timestamp:{label}") from exc
    if result.tzinfo is None:
        raise ValueError(f"timezone_missing:{label}")
    return result


def _duration(payload: Mapping[str, Any], label: str) -> tuple[datetime, datetime, float]:
    started = _parse_datetime(payload.get("started_at"), f"{label}:started_at")
    finished = _parse_datetime(payload.get("finished_at"), f"{label}:finished_at")
    seconds = (finished - started).total_seconds()
    if seconds < 0:
        raise ValueError(f"negative_duration:{label}")
    return started, finished, seconds


def _exception_type(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or "unknown_exception"
    if isinstance(value, Mapping):
        for key in ("exception_type", "type", "name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return "unknown_exception"


def _reward(payload: Mapping[str, Any]) -> float:
    verifier = payload.get("verifier_result")
    if not isinstance(verifier, Mapping):
        raise ValueError("missing_verifier_result")
    rewards = verifier.get("rewards")
    if not isinstance(rewards, Mapping) or not rewards:
        raise ValueError("missing_reward")
    value = next(iter(rewards.values()))
    if isinstance(value, bool):
        raise ValueError("invalid_reward")
    try:
        reward = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_reward") from exc
    if not math.isfinite(reward):
        raise ValueError("invalid_reward")
    return reward


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _iter_strings(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _iter_strings(nested)


def _skill_names(arguments: Any) -> set[str]:
    if not isinstance(arguments, Mapping):
        return set()
    names: set[str] = set()
    for key in ("skill", "skill_name", "name"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            names.add(value.strip())
        elif isinstance(value, list):
            names.update(item.strip() for item in value if isinstance(item, str) and item.strip())
    if names:
        return names
    for text in _iter_strings(arguments):
        names.update(match.group(1) for match in _SKILL_PATH_PATTERN.finditer(text))
    return names


def _analyze_skill_usage(path: Path) -> tuple[int, list[str]]:
    if not path.is_file():
        return 0, []
    try:
        trajectory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, []
    steps = trajectory.get("steps") if isinstance(trajectory, Mapping) else None
    if not isinstance(steps, list):
        return 0, []
    calls = 0
    names: set[str] = set()
    for step in steps:
        tool_calls = step.get("tool_calls") if isinstance(step, Mapping) else None
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, Mapping):
                continue
            function = tool_call.get("function_name") or tool_call.get("name") or ""
            normalized = function.strip().lower() if isinstance(function, str) else ""
            arguments = tool_call.get("arguments")
            extracted = _skill_names(arguments)
            explicit_skill = normalized == "skill"
            direct_read = normalized in {"read", "readfile"} and bool(extracted)
            shell_read = any(
                _SKILL_PATH_PATTERN.search(text) and _SHELL_READ_PATTERN.search(text)
                for text in _iter_strings(arguments)
            )
            if explicit_skill or direct_read or shell_read:
                calls += 1
                names.update(extracted)
    return calls, sorted(names)


def _load_patch_history(
    path: Path,
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    rows: dict[str, Mapping[str, Any]] = {}
    reasons: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            reasons.append(f"invalid_patch_history_json:line-{line_number}")
            continue
        if not isinstance(row, Mapping):
            reasons.append(f"invalid_patch_history_row:line-{line_number}")
            continue
        task_id = row.get("task_name")
        if not isinstance(task_id, str) or not task_id.strip():
            reasons.append(f"missing_patch_task_id:line-{line_number}")
            continue
        task_id = task_id.strip()
        if task_id in rows:
            reasons.append(f"duplicate_patch_record:{task_id}")
            continue
        rows[task_id] = row
    return rows, reasons


def _patch_is_nonempty(row: Mapping[str, Any]) -> bool:
    upserts = row.get("upsert_paths")
    deletes = row.get("delete_paths")
    applied = row.get("applied")
    if isinstance(applied, Mapping):
        return bool(applied.get("upserted")) or bool(applied.get("deleted"))
    changed = bool(upserts) or bool(deletes)
    status = row.get("status")
    return changed and status == "applied"


def _patch_duration(row: Mapping[str, Any], task_id: str) -> tuple[float | None, str | None]:
    has_any = "started_at" in row or "finished_at" in row
    if not has_any:
        return None, None
    try:
        _, _, seconds = _duration(row, f"patch:{task_id}")
    except ValueError as exc:
        return None, str(exc)
    return seconds, None


def _token_usage(job_dir: Path) -> tuple[SkillFlowTokenUsage, list[str]]:
    reasons: list[str] = []
    try:
        summary = aggregate_token_usage(job_dir / "token_usage")
    except (OSError, ValueError) as exc:
        return _invalid_token_usage(), [f"token_ledger_error:{type(exc).__name__}"]
    attempted = int(summary["attempted_calls"])
    observed = int(summary["observed_calls"])
    coverage = float(summary["observed_coverage"])
    billed = summary["billed_tokens"]
    usage = SkillFlowTokenUsage(
        attempted_calls=attempted,
        observed_calls=observed,
        observed_coverage=coverage,
        prompt_tokens=int(billed["prompt_tokens"]),
        completion_tokens=int(billed["completion_tokens"]),
        total_tokens=int(billed["total_tokens"]),
    )
    if attempted == 0:
        reasons.append("missing_token_usage")
    elif coverage != 1.0:
        reasons.append(f"invalid_token_coverage:{coverage:.6f}")
    return usage, reasons


def parse_arm_result(
    job_dir: Path | str,
    family_manifest: SkillFlowFamilyManifest,
    *,
    arm: ArmName,
    replicate_id: ReplicateId,
    expected_task_checksums: Mapping[str, str] | None = None,
) -> SkillFlowArmResult:
    """Parse one isolated Harbor arm and retain all typed validity failures."""

    root = Path(job_dir)
    reasons: list[str] = []
    if family_manifest.status != "ready":
        reasons.extend(f"input_invalid:{reason}" for reason in family_manifest.invalid_reasons)

    expected_ids = [task.task_id for task in family_manifest.tasks]
    trial_payloads: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    top_result = root / "result.json"
    if not top_result.is_file():
        reasons.append("missing_job_result")
    else:
        try:
            top_payload = json.loads(top_result.read_text(encoding="utf-8"))
            total = top_payload.get("n_total_trials") if isinstance(top_payload, Mapping) else None
            if total is not None and total != len(expected_ids):
                reasons.append(f"job_trial_count_mismatch:{total}!={len(expected_ids)}")
        except (OSError, json.JSONDecodeError):
            reasons.append("invalid_job_result")

    if root.is_dir():
        for child in sorted(root.iterdir()):
            result_path = child / "result.json"
            if not child.is_dir() or not result_path.is_file():
                continue
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                reasons.append(f"invalid_trial_result:{child.name}")
                continue
            task_id = payload.get("task_name") if isinstance(payload, Mapping) else None
            if not isinstance(task_id, str) or not task_id.strip():
                reasons.append(f"missing_task_id:{child.name}")
                continue
            task_id = task_id.strip()
            if task_id in trial_payloads:
                reasons.append(f"duplicate_task:{task_id}")
                continue
            trial_payloads[task_id] = (child, payload)

    for task_id in expected_ids:
        if task_id not in trial_payloads:
            reasons.append(f"missing_task:{task_id}")
    for task_id in sorted(set(trial_payloads) - set(expected_ids)):
        reasons.append(f"unexpected_task:{task_id}")

    patch_rows: dict[str, Mapping[str, Any]] = {}
    if arm == "clean_evolution":
        history_path = root / "skill_patch_history.jsonl"
        if not history_path.is_file():
            reasons.append("missing_patch_history")
        else:
            loaded_rows, patch_reasons = _load_patch_history(history_path)
            patch_rows = loaded_rows
            reasons.extend(patch_reasons)
            for task_id in expected_ids:
                if task_id not in patch_rows:
                    reasons.append(f"missing_patch_record:{task_id}")
            for task_id in sorted(set(patch_rows) - set(expected_ids)):
                reasons.append(f"unexpected_patch_record:{task_id}")

    task_results: list[SkillFlowTaskResult] = []
    for task in family_manifest.tasks:
        found = trial_payloads.get(task.task_id)
        if found is None:
            continue
        trial_dir, payload = found
        checksum = payload.get("task_checksum")
        if not isinstance(checksum, str) or not checksum.strip():
            reasons.append(f"missing_task_checksum:{task.task_id}")
            continue
        expected_checksum = (
            expected_task_checksums.get(task.task_id)
            if expected_task_checksums is not None
            else None
        )
        if expected_checksum is not None and checksum != expected_checksum:
            reasons.append(f"task_checksum_mismatch:{task.task_id}")
            continue
        exception = _exception_type(payload.get("exception_info"))
        try:
            reward = _reward(payload)
        except ValueError as exc:
            label = str(exc)
            if exception is not None and label.startswith("missing_"):
                reasons.append(f"execution_exception:{task.task_id}:{exception}")
            reasons.append(f"{label}:{task.task_id}")
            continue
        try:
            started, finished, duration = _duration(payload, f"task:{task.task_id}")
            agent = payload.get("agent_execution")
            verifier = payload.get("verifier")
            if not isinstance(agent, Mapping):
                raise ValueError(f"missing_timing:agent:{task.task_id}")
            if not isinstance(verifier, Mapping):
                raise ValueError(f"missing_timing:verifier:{task.task_id}")
            _, _, agent_duration = _duration(agent, f"agent:{task.task_id}")
            _, _, verifier_duration = _duration(verifier, f"verifier:{task.task_id}")
        except ValueError as exc:
            reasons.append(str(exc))
            continue
        patch_duration: float | None = None
        if arm == "clean_evolution" and task.task_id in patch_rows:
            patch_duration, patch_reason = _patch_duration(patch_rows[task.task_id], task.task_id)
            if patch_reason is not None:
                reasons.append(patch_reason)
        skill_calls, skills_used = _analyze_skill_usage(
            trial_dir / "agent" / "trajectory.json"
        )
        task_results.append(
            SkillFlowTaskResult(
                task_id=task.task_id,
                order=task.order,
                reward=reward,
                task_checksum=checksum,
                started_at=started,
                finished_at=finished,
                duration_seconds=duration,
                agent_duration_seconds=agent_duration,
                verifier_duration_seconds=verifier_duration,
                patch_duration_seconds=patch_duration,
                skill_use_calls=skill_calls,
                skills_used=skills_used,
                exception_type=exception,
            )
        )

    token_usage, token_reasons = _token_usage(root)
    reasons.extend(token_reasons)
    reasons = list(dict.fromkeys(reasons))
    starts = [task.started_at for task in task_results]
    finishes = [task.finished_at for task in task_results]
    started_at = min(starts) if starts else None
    finished_at = max(finishes) if finishes else None
    duration_seconds = (
        (finished_at - started_at).total_seconds()
        if started_at is not None and finished_at is not None
        else None
    )
    nonempty_patch_count = sum(_patch_is_nonempty(row) for row in patch_rows.values())
    used_after_first = sum(task.skill_use_calls > 0 for task in task_results if task.order >= 2)
    return SkillFlowArmResult(
        family=family_manifest.family,
        replicate_id=replicate_id,
        arm=arm,
        complete=not reasons,
        invalid_reasons=reasons,
        task_results=task_results,
        task_rewards=[task.reward for task in task_results],
        patch_count=len(patch_rows),
        nonempty_patch_count=nonempty_patch_count,
        skill_used_task_count=used_after_first,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        token_usage=token_usage,
    )


def pair_replicate(
    base: SkillFlowArmResult, evolution: SkillFlowArmResult
) -> SkillFlowReplicateResult:
    """Pair two isolated arms; never compute efficacy for an invalid pair."""

    reasons: list[str] = []
    if base.family != evolution.family:
        reasons.append("family_mismatch")
    if base.replicate_id != evolution.replicate_id:
        reasons.append("replicate_mismatch")
    reasons.extend(f"base:{reason}" for reason in base.invalid_reasons)
    reasons.extend(f"clean_evolution:{reason}" for reason in evolution.invalid_reasons)
    base_ids = [task.task_id for task in base.task_results]
    evolution_ids = [task.task_id for task in evolution.task_results]
    if base_ids != evolution_ids:
        reasons.append("paired_task_order_mismatch")
    base_checksums = [task.task_checksum for task in base.task_results]
    evolution_checksums = [task.task_checksum for task in evolution.task_results]
    if base_ids == evolution_ids and base_checksums != evolution_checksums:
        reasons.append("paired_task_checksum_mismatch")
    reasons = list(dict.fromkeys(reasons))
    delta_late: float | None = None
    delta_full: float | None = None
    if not reasons:
        if len(base.task_rewards) < 2:
            reasons.append("insufficient_late_tasks")
        else:
            delta_late = fmean(evolution.task_rewards[1:]) - fmean(base.task_rewards[1:])
            delta_full = fmean(evolution.task_rewards) - fmean(base.task_rewards)
    return SkillFlowReplicateResult(
        family=base.family,
        replicate_id=base.replicate_id,
        complete=not reasons,
        invalid_reasons=reasons,
        base=base,
        evolution=evolution,
        delta_late=delta_late,
        delta_full=delta_full,
    )


__all__ = [
    "ArmName",
    "ReplicateId",
    "SkillFlowArmResult",
    "SkillFlowReplicateResult",
    "SkillFlowTaskResult",
    "SkillFlowTokenUsage",
    "pair_replicate",
    "parse_arm_result",
]
