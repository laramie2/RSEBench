"""Pinned OfficeQA scoring semantics and rollout failure taxonomy.

The hard-score behavior is a compact, runtime-independent implementation of
the released ``databricks/officeqa`` reward policy: direct answers only,
ordered numeric comparison, compatible units, and relative numeric tolerance.
The benchmark lane pins tolerance to 1% at its call sites.
"""

from __future__ import annotations

import re
import string
from typing import Literal

from pydantic import Field

from rsebench.contracts import StrictModel


FailureCategory = Literal[
    "correct",
    "missing_oracle_page",
    "external_evidence_required",
    "tool_budget_exhausted",
    "answer_missing",
    "provider_failure",
    "incorrect_answer",
]

_CURRENCY_SYMBOLS = r"$£€¥₹¢₩₽"
_NUMBER_BODY = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_NUMBER_RE = re.compile(rf"-?{_NUMBER_BODY}%?")
_ANSWER_RE = re.compile(
    r"<(?:answer|final_answer)>\s*(.*?)\s*</(?:answer|final_answer)>",
    re.IGNORECASE | re.DOTALL,
)
_UNIT_WORDS = (
    "trillion",
    "trillions",
    "billion",
    "billions",
    "million",
    "millions",
    "thousand",
    "thousands",
    "hundred",
    "hundreds",
    "dollar",
    "dollars",
    "nominal",
    "percent",
    "percentage",
)
_PROVIDER_FAILURE_RE = re.compile(
    r"(?:provider|apierror|authentication|rate.?limit|http\s*[45]\d\d|"
    r"connection|timeout|temporarily unavailable|service unavailable)",
    re.IGNORECASE,
)
_BUDGET_RE = re.compile(
    r"(?:exceeded|exhausted|final round).*?(?:turn|round).*?budget|"
    r"(?:tool|codex)-turn budget|final round.*without",
    re.IGNORECASE,
)
_MISSING_ANSWER_RE = re.compile(
    r"(?:did not produce|neither produced|without).*?(?:final )?answer",
    re.IGNORECASE,
)


class OfficeQAScore(StrictModel):
    hard: float = Field(ge=0.0, le=1.0)
    exact: float = Field(ge=0.0, le=1.0)
    predicted_answer: str
    gold_answer: str
    rationale: str


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace("\u2212", "-")).strip()


def _extract_answer(text: str) -> str:
    matches = list(_ANSWER_RE.finditer(str(text or "")))
    return _normalize_text(matches[-1].group(1) if matches else str(text or ""))


def _numeric_text(text: str) -> str:
    normalized = _normalize_text(text)

    def accounting(match: re.Match[str]) -> str:
        number = match.group(1)
        numeric = float(number.replace(",", ""))
        if 1900 <= numeric <= 2100 and numeric.is_integer():
            return match.group(0)
        return f"-{number}"

    normalized = re.sub(rf"\(\s*[{_CURRENCY_SYMBOLS}]?\s*({_NUMBER_BODY})\s*\)", accounting, normalized)
    return re.sub(rf"[{_CURRENCY_SYMBOLS}]", "", normalized)


def _numbers(text: str) -> list[tuple[float, str, bool]]:
    normalized = _numeric_text(text)
    values: list[tuple[float, str, bool]] = []
    for match in _NUMBER_RE.finditer(normalized):
        raw = match.group()
        value = float(raw.rstrip("%").replace(",", ""))
        start = max(0, match.start() - 20)
        end = min(len(normalized), match.end() + 20)
        values.append((value, normalized[start:end].casefold(), raw.endswith("%")))
    return values


def _segmented_numeric_values(text: str, expected_len: int) -> list[list[float]]:
    """Resolve comma ambiguity in one bracketed list using the gold arity."""

    match = re.fullmatch(r"\s*\[([^\[\]]+)\]\s*", _numeric_text(text))
    if match is None or expected_len < 2:
        return []
    body = match.group(1)
    comma_positions = [item.start() for item in re.finditer(",", body)]
    spans: list[tuple[int, int]] = []
    start = 0
    for position in comma_positions:
        spans.append((start, position))
        start = position + 1
    spans.append((start, len(body)))
    if len(spans) < expected_len:
        return []

    def parse_chunk(start_index: int, end_index: int) -> float | None:
        chunk = body[spans[start_index][0] : spans[end_index - 1][1]].strip()
        if not chunk or _NUMBER_RE.fullmatch(chunk) is None:
            return None
        return float(chunk.rstrip("%").replace(",", ""))

    def search(chunk_index: int, remaining: int) -> list[list[float]]:
        if remaining == 0:
            return [[]] if chunk_index == len(spans) else []
        results: list[list[float]] = []
        maximum_end = len(spans) - remaining + 1
        for end_index in range(chunk_index + 1, maximum_end + 1):
            value = parse_chunk(chunk_index, end_index)
            if value is None:
                continue
            for tail in search(end_index, remaining - 1):
                results.append([value, *tail])
        return results

    return search(0, expected_len)


def _prediction_number_candidates(
    predicted: str, expected_len: int
) -> list[list[tuple[float, str, bool]]]:
    extracted = _numbers(predicted)
    candidates = [extracted] if len(extracted) == expected_len else []
    candidates.extend(
        [(value, "", False) for value in values]
        for values in _segmented_numeric_values(predicted, expected_len)
    )
    return candidates


def _unit(context: str) -> str | None:
    for name in ("trillion", "billion", "million", "thousand"):
        if re.search(rf"\b{name}s?\b", context):
            return name
    for abbreviation, name in (("b", "billion"), ("m", "million"), ("k", "thousand")):
        if re.search(rf"\b{abbreviation}\b", context):
            return name
    return None


def _text_residue(text: str) -> str:
    residue = _NUMBER_RE.sub(" ", _numeric_text(text).casefold())
    for word in _UNIT_WORDS:
        residue = re.sub(rf"\b{word}\b", " ", residue)
    residue = re.sub(r"[^\w]+", " ", residue)
    return " ".join(residue.split())


def _normalized_exact(text: str) -> str:
    value = _extract_answer(text).casefold().replace(",", "")
    allowed_numeric = set("0123456789.-")
    value = "".join(
        character
        for character in value
        if character not in string.punctuation
        or character in allowed_numeric
        or character == "%"
    )
    value = re.sub(
        r"\b(million|millions|billion|billions|dollars|dollar|nominal)\b",
        " ",
        value,
    )
    return " ".join(value.split())


def _direct_answer_valid(gold: str, predicted: str) -> tuple[bool, str]:
    if not predicted:
        return False, "predicted answer is empty"
    if len([line for line in predicted.splitlines() if line.strip()]) > 1:
        return False, "predicted answer spans multiple lines"
    if len(predicted) > 250:
        return False, "predicted answer is longer than 250 characters"
    if re.search(r"<[^>]*>", predicted):
        return False, "predicted answer contains markup"
    gold_numbers = _numbers(gold)
    predicted_numbers = _numbers(predicted)
    if gold_numbers and not _prediction_number_candidates(predicted, len(gold_numbers)):
        return False, "predicted answer has the wrong number of numeric values"
    if not gold_numbers and predicted_numbers:
        return False, "text-only answer contains unexpected numbers"
    return True, "direct answer only"


def score_officeqa_details(
    gold: str, prediction: str, *, tolerance: float = 0.01
) -> OfficeQAScore:
    """Return the pinned hard score plus an exact-match diagnostic."""

    if not 0.0 <= tolerance <= 1.0:
        raise ValueError("tolerance must be between zero and one")
    gold_answer = _normalize_text(gold)
    predicted_answer = _extract_answer(prediction)
    exact = float(_normalized_exact(predicted_answer) == _normalized_exact(gold_answer))
    valid, rationale = _direct_answer_valid(gold_answer, predicted_answer)
    if not valid or "unable to determine" in predicted_answer.casefold():
        return OfficeQAScore(
            hard=0.0,
            exact=exact,
            predicted_answer=predicted_answer,
            gold_answer=gold_answer,
            rationale=rationale,
        )

    gold_numbers = _numbers(gold_answer)
    if gold_numbers:
        gold_text = _text_residue(gold_answer)
        predicted_text = _text_residue(predicted_answer)
        if gold_text and gold_text not in predicted_text and predicted_text not in gold_text:
            return OfficeQAScore(
                hard=0.0,
                exact=exact,
                predicted_answer=predicted_answer,
                gold_answer=gold_answer,
                rationale=f"text residue mismatch: {gold_text!r} vs {predicted_text!r}",
            )
        mismatch = "no numeric candidate matched"
        for predicted_numbers in _prediction_number_candidates(
            predicted_answer, len(gold_numbers)
        ):
            candidate_matches = True
            for (gold_value, gold_context, _), (
                predicted_value,
                predicted_context,
                _,
            ) in zip(gold_numbers, predicted_numbers, strict=True):
                gold_unit = _unit(gold_context)
                predicted_unit = _unit(predicted_context)
                if gold_unit and predicted_unit and gold_unit != predicted_unit:
                    mismatch = f"unit mismatch: {gold_unit} vs {predicted_unit}"
                    candidate_matches = False
                    break
                difference = (
                    abs(predicted_value)
                    if gold_value == 0 and predicted_value != 0
                    else (
                        0.0
                        if gold_value == 0
                        else abs(gold_value - predicted_value) / abs(gold_value)
                    )
                )
                if difference > tolerance:
                    mismatch = (
                        f"numeric relative difference {difference:.6f} exceeds tolerance"
                    )
                    candidate_matches = False
                    break
            if candidate_matches:
                break
        else:
            return OfficeQAScore(
                hard=0.0,
                exact=exact,
                predicted_answer=predicted_answer,
                gold_answer=gold_answer,
                rationale=mismatch,
            )
        rationale = f"{len(gold_numbers)} ordered numeric value(s) within tolerance"
    else:
        gold_text = _text_residue(gold_answer)
        predicted_text = _text_residue(predicted_answer)
        if gold_text != predicted_text:
            return OfficeQAScore(
                hard=0.0,
                exact=exact,
                predicted_answer=predicted_answer,
                gold_answer=gold_answer,
                rationale=f"text mismatch: {gold_text!r} vs {predicted_text!r}",
            )
        rationale = "normalized text match"
    return OfficeQAScore(
        hard=1.0,
        exact=exact,
        predicted_answer=predicted_answer,
        gold_answer=gold_answer,
        rationale=rationale,
    )


def score_officeqa(gold: str, prediction: str, *, tolerance: float = 0.01) -> float:
    return score_officeqa_details(gold, prediction, tolerance=tolerance).hard


def classify_officeqa_failure(
    *,
    hard_score: float,
    predicted_answer: str,
    fail_reason: str,
    oracle_parsed_pages_included: bool,
    expects_oracle_pages: bool = True,
    external_evidence_required: bool = False,
) -> FailureCategory:
    """Assign exactly one outcome category using auditable rollout fields."""

    if hard_score >= 1.0:
        return "correct"
    reason = str(fail_reason or "")
    if _PROVIDER_FAILURE_RE.search(reason):
        return "provider_failure"
    if expects_oracle_pages and not oracle_parsed_pages_included:
        return "missing_oracle_page"
    if external_evidence_required:
        return "external_evidence_required"
    if _BUDGET_RE.search(reason):
        return "tool_budget_exhausted"
    if not str(predicted_answer or "").strip() or _MISSING_ANSWER_RE.search(reason):
        return "answer_missing"
    return "incorrect_answer"
