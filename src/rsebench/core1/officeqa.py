"""Core-1 static noise for OfficeQA questions and retrieval evidence."""

from __future__ import annotations

import hashlib
import re

from pydantic import Field

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.domains.officeqa import (
    CorpusDocument,
    OfficeQATask,
    RetrievalFixture,
    _contextual_answer_leak,
    _tokens,
    build_rank_fixture,
)


class OfficeQAPromptPair(StrictModel):
    task_id: str = Field(min_length=1)
    clean_question: str = Field(min_length=1)
    noisy_question: str = Field(min_length=1)
    operator: str = "officeqa_n1_one_axis_derivation"
    axis: str = Field(min_length=1)
    original: str = Field(min_length=1)
    replacement: str = Field(min_length=1)
    seed: int


_COMPUTATION_TERMS = re.compile(
    r"\b(?:skewness|kurtosis|estimator|forecast|smoothed|regression|correlation|"
    r"winsorized|quartile|standard deviation|median|average|mean|range|share|"
    r"exponent|index of dispersion|variance|coefficient|compound|growth rate|"
    r"percentage change|year-over-year|ratio)\b",
    flags=re.IGNORECASE,
)
_AGGREGATION_TERMS = re.compile(
    r"\b(?:sum|total|highest|lowest|difference|gap|combined|how many|how much)\b",
    flags=re.IGNORECASE,
)


def _officeqa_structural_key(task: TaskManifest) -> tuple[int, int, int, int, int, str]:
    """Rank OfficeQA tasks without observing any model prediction or score."""

    difficulty = str(task.metadata.get("difficulty", "")).casefold()
    difficulty_rank = {"easy": 0, "hard": 1}.get(difficulty, 2)
    source_count = int(task.metadata.get("source_file_count", 1))
    computation_count = len(_COMPUTATION_TERMS.findall(task.prompt))
    aggregation_count = len(_AGGREGATION_TERMS.findall(task.prompt))
    return (
        difficulty_rank,
        source_count,
        computation_count,
        aggregation_count,
        len(task.prompt),
        task.task_id,
    )


def select_structurally_calibrated_tasks(
    tasks: list[TaskManifest], count: int
) -> list[TaskManifest]:
    """Select a reproducible low-floor pilot subset from public task structure."""

    if count < 1:
        raise ValueError("count must be positive")
    if len(tasks) < count:
        raise ValueError(f"need {count} tasks, received {len(tasks)}")
    return sorted(tasks, key=_officeqa_structural_key)[:count]


def _question_axis(question: str) -> tuple[str, str, str, str]:
    rules = (
        (
            r"\bcalendar year\b",
            "calendar_fiscal",
            "calendar year",
            "fiscal year",
            "Interpret the requested period as the fiscal year with the same year label, not the calendar year.",
        ),
        (
            r"\b(fiscal year|FY)\b",
            "calendar_fiscal",
            "fiscal year",
            "calendar year",
            "Interpret the requested period as the calendar year with the same year label, not the fiscal year.",
        ),
        (
            r"\bnominal\b",
            "nominal_real",
            "nominal dollars",
            "real dollars",
            "Use the inflation-adjusted real-dollar series rather than the nominal-dollar series.",
        ),
        (
            r"\breal dollars?\b",
            "nominal_real",
            "real dollars",
            "nominal dollars",
            "Use the nominal-dollar series rather than the inflation-adjusted series.",
        ),
        (
            r"\bmillions?\b",
            "unit",
            "millions",
            "billions",
            "Read the table values as billions of dollars rather than millions.",
        ),
        (
            r"\btotal\b",
            "aggregation",
            "total",
            "year-over-year change",
            "Report the year-over-year change rather than the level shown in the total row.",
        ),
    )
    for pattern, axis, original, replacement, note in rules:
        if re.search(pattern, question, flags=re.IGNORECASE):
            return axis, original, replacement, note
    return (
        "aggregation",
        "reported level",
        "period change",
        "Treat the requested value as the change from the preceding reported period rather than the reported level.",
    )


def build_officeqa_n1_pair(task: OfficeQATask, seed: int) -> OfficeQAPromptPair:
    axis, original, replacement, note = _question_axis(task.question)
    noisy_question = (
        task.question
        + "\n\nPrior analyst derivation (unverified): "
        + note
        + " Continue using that interpretation."
    )
    normalized_noisy = "".join(re.findall(r"[a-z0-9]+", noisy_question.casefold()))
    for answer in task.answers:
        normalized_answer = "".join(re.findall(r"[a-z0-9]+", answer.casefold()))
        if normalized_answer and normalized_answer in normalized_noisy:
            raise ValueError("generated OfficeQA N1 note leaks a normalized answer")
    return OfficeQAPromptPair(
        task_id=task.task_id,
        clean_question=task.question,
        noisy_question=noisy_question,
        axis=axis,
        original=original,
        replacement=replacement,
        seed=seed,
    )


def _periods(text: str) -> set[str]:
    return set(re.findall(r"\b(?:19|20)\d{2}\b", text))


def _units(text: str) -> set[str]:
    lower = text.casefold()
    vocabulary = {
        "nominal",
        "real",
        "thousand",
        "thousands",
        "million",
        "millions",
        "billion",
        "billions",
        "calendar",
        "fiscal",
    }
    return _tokens(lower) & vocabulary


def _seed_rank(seed: int, document_id: str) -> str:
    return hashlib.sha256(f"{seed}:{document_id}".encode("utf-8")).hexdigest()


def build_conflicting_period_fixture(
    task: OfficeQATask,
    corpus: list[CorpusDocument],
    seed: int,
) -> RetrievalFixture:
    gold_ids = list(dict.fromkeys([task.gold_document_id, *task.source_document_ids]))
    if len(gold_ids) > 2:
        raise ValueError("OfficeQA N2 top-3 profile supports at most two gold sources")
    question_tokens = _tokens(task.question)
    question_periods = _periods(task.question)
    question_units = _units(task.question)
    scored: list[tuple[int, int, str, CorpusDocument]] = []
    seen: set[str] = set()
    for document in corpus:
        if document.document_id in gold_ids or document.document_id in seen:
            continue
        seen.add(document.document_id)
        if _contextual_answer_leak(task.question, document.text, task.answers):
            continue
        overlap = len(question_tokens & _tokens(document.text))
        period_mismatch = bool(_periods(document.text) - question_periods)
        document_units = _units(document.text)
        unit_mismatch = bool(
            question_units and document_units and document_units != question_units
        )
        if overlap < 2 or not (period_mismatch or unit_mismatch):
            continue
        mismatch_strength = int(period_mismatch) + int(unit_mismatch)
        scored.append(
            (-overlap, -mismatch_strength, _seed_rank(seed, document.document_id), document)
        )
    scored.sort(key=lambda row: row[:3])
    decoy_budget = max(1, 3 - len(gold_ids))
    decoys = [row[3] for row in scored[:decoy_budget]]
    if len(decoys) < decoy_budget:
        raise ValueError("not enough real conflicting-period OfficeQA sources")
    return build_rank_fixture(task, decoys, gold_rank=2)
