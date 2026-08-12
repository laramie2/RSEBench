"""Deterministic OfficeQA runtime calibration and pilot freezing."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel


EVIDENCE_RULE_VERSION = "officeqa-offline-evidence-v1"
_EXTERNAL_EVIDENCE_PATTERNS = (
    r"\bbls\b",
    r"\bbureau of labor statistics\b",
    r"\bcpi[ -]?u\b",
    r"\bfederal reserve bank of minneapolis\b",
    r"\bmacrotrends\b",
    r"\bfred data\b",
)


class OfficeQARuntime(StrictModel):
    name: str = Field(min_length=1)
    max_tool_turns: int = Field(ge=1)
    max_completion_tokens: int = Field(ge=1)


class OfficeQACalibrationReport(StrictModel):
    runtime: OfficeQARuntime
    n_tasks: int = Field(ge=1)
    score: float = Field(ge=0.0, le=1.0)
    parseable_answer_rate: float = Field(ge=0.0, le=1.0)
    systemic_failure_rate: float = Field(ge=0.0, le=1.0)
    oracle_parsed_pages_rate: float = Field(ge=0.0, le=1.0)
    eligible_count: int = Field(ge=0)
    failure_category_counts: dict[str, int] = Field(default_factory=dict)
    evaluation_dir: str | None = None
    error: str | None = None


class OfficeQACalibrationRun(StrictModel):
    run_dir: str
    status: str
    calibration_ids: list[str]
    evidence_eligibility: dict[str, "EvidenceEligibility"]
    reports: list[OfficeQACalibrationReport]
    selected_runtime: OfficeQARuntime | None = None


class EvidenceEligibility(StrictModel):
    task_id: str = Field(min_length=1)
    eligible: bool
    reason: str = Field(min_length=1)
    rule_version: str = EVIDENCE_RULE_VERSION
    matched_patterns: list[str] = Field(default_factory=list)


class OfficeQAPilotSplit(StrictModel):
    benchmark: str = "officeqa_full"
    seed: int
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration: list[str]
    evolution: list[str]
    validation: list[str]
    test: list[str]
    strata: dict[str, str]
    evidence_eligibility: dict[str, EvidenceEligibility]

    @property
    def all_ids(self) -> list[str]:
        return self.evolution + self.validation + self.test

    @model_validator(mode="after")
    def validate_disjoint(self) -> "OfficeQAPilotSplit":
        partitions = [self.calibration, self.evolution, self.validation, self.test]
        flattened = [task_id for partition in partitions for task_id in partition]
        if len(flattened) != len(set(flattened)):
            raise ValueError("OfficeQA calibration and pilot partitions must be disjoint")
        if not all(self.evidence_eligibility[task_id].eligible for task_id in self.all_ids):
            raise ValueError("OfficeQA pilot contains an ineligible task")
        return self


def _task_id(row: Mapping[str, Any]) -> str:
    value = str(row.get("uid") or row.get("id") or "").strip()
    if not value:
        raise ValueError("OfficeQA row has no uid")
    return value


def _source_file_count(value: Any) -> int:
    if isinstance(value, (list, tuple)):
        return len([item for item in value if str(item).strip()])
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0
    text = str(value).strip()
    if not text:
        return 0
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return len([item for item in parsed if str(item).strip()])
    return len([item for item in text.replace("\\r\\n", "\n").splitlines() if item.strip()])


def officeqa_stratum(row: Mapping[str, Any]) -> str:
    difficulty = str(row.get("difficulty") or "unknown").strip().casefold()
    count = _source_file_count(row.get("source_files"))
    count_bin = "1" if count <= 1 else ("2-3" if count <= 3 else "4+")
    return f"{difficulty}|files={count_bin}"


def _seeded_order(task_id: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{task_id}".encode("utf-8")).hexdigest()


def _stratified_select(
    rows: Iterable[Mapping[str, Any]],
    *,
    size: int,
    seed: int,
    excluded_ids: set[str] | None = None,
) -> list[str]:
    excluded = excluded_ids or set()
    groups: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        task_id = _task_id(row)
        if task_id in excluded:
            continue
        if task_id in seen:
            raise ValueError(f"duplicate OfficeQA uid: {task_id}")
        seen.add(task_id)
        groups[officeqa_stratum(row)].append(task_id)
    for task_ids in groups.values():
        task_ids.sort(key=lambda task_id: (_seeded_order(task_id, seed), task_id))
    selected: list[str] = []
    offsets = {name: 0 for name in groups}
    while len(selected) < size:
        progressed = False
        for name in sorted(groups):
            offset = offsets[name]
            if offset >= len(groups[name]):
                continue
            selected.append(groups[name][offset])
            offsets[name] += 1
            progressed = True
            if len(selected) == size:
                break
        if not progressed:
            raise ValueError(
                f"OfficeQA has only {len(selected)} selectable rows, requested {size}"
            )
    return selected


def select_officeqa_calibration_ids(
    rows: Iterable[Mapping[str, Any]], *, size: int = 30, seed: int = 20260812
) -> list[str]:
    return _stratified_select(rows, size=size, seed=seed)


def officeqa_evidence_eligibility(row: Mapping[str, Any]) -> EvidenceEligibility:
    """Classify offline evidence availability without observing task correctness."""

    task_id = _task_id(row)
    question = str(row.get("question") or "").casefold()
    matched = [pattern for pattern in _EXTERNAL_EVIDENCE_PATTERNS if re.search(pattern, question)]
    return EvidenceEligibility(
        task_id=task_id,
        eligible=not matched,
        reason="oracle_local" if not matched else "external_evidence_required",
        matched_patterns=matched,
    )


def select_runtime(
    reports: Iterable[OfficeQACalibrationReport],
    *,
    score_low: float = 0.25,
    score_high: float = 0.75,
    min_parseable_rate: float = 0.80,
    max_systemic_failure_rate: float = 0.05,
    min_eligible_count: int = 12,
) -> OfficeQACalibrationReport | None:
    """Return the first declared runtime satisfying all calibration gates."""

    for report in reports:
        if (
            score_low <= report.score <= score_high
            and report.parseable_answer_rate >= min_parseable_rate
            and report.systemic_failure_rate < max_systemic_failure_rate
            and report.eligible_count >= min_eligible_count
            and not report.error
        ):
            return report
    return None


def freeze_officeqa_pilot(
    rows: Iterable[Mapping[str, Any]],
    calibration_ids: Iterable[str],
    *,
    seed: int,
    train_size: int = 12,
    validation_size: int = 6,
    test_size: int = 20,
) -> OfficeQAPilotSplit:
    """Freeze an eligible, stratified pilot without using correctness outcomes."""

    row_list = list(rows)
    by_id = {_task_id(row): row for row in row_list}
    calibration = [str(task_id) for task_id in calibration_ids]
    missing = [task_id for task_id in calibration if task_id not in by_id]
    if missing:
        raise ValueError(f"calibration IDs missing from OfficeQA rows: {missing[:3]}")
    eligibility = {
        task_id: officeqa_evidence_eligibility(row)
        for task_id, row in by_id.items()
    }
    eligible_rows = [
        row
        for task_id, row in by_id.items()
        if task_id not in set(calibration) and eligibility[task_id].eligible
    ]
    requested = train_size + validation_size + test_size
    if len(eligible_rows) < requested:
        raise ValueError(
            f"OfficeQA has {len(eligible_rows)} eligible non-calibration rows; "
            f"{requested} required"
        )
    selected = _stratified_select(eligible_rows, size=requested, seed=seed)
    canonical_rows = [
        {
            "uid": task_id,
            "stratum": officeqa_stratum(by_id[task_id]),
            "eligibility": eligibility[task_id].model_dump(mode="json"),
        }
        for task_id in sorted(by_id)
    ]
    source_hash = hashlib.sha256(
        json.dumps(
            canonical_rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    return OfficeQAPilotSplit(
        seed=seed,
        source_hash=source_hash,
        calibration=calibration,
        evolution=selected[:train_size],
        validation=selected[train_size : train_size + validation_size],
        test=selected[train_size + validation_size :],
        strata={task_id: officeqa_stratum(by_id[task_id]) for task_id in by_id},
        evidence_eligibility=eligibility,
    )
