from __future__ import annotations

import pytest

from rsebench.evolution.calibration import (
    OfficeQACalibrationReport,
    OfficeQARuntime,
    freeze_officeqa_pilot,
    officeqa_evidence_eligibility,
    officeqa_stratum,
    select_officeqa_calibration_ids,
    select_runtime,
)


def _report(
    name: str,
    *,
    score: float,
    parsed: float,
    systemic: float,
    eligible: int,
) -> OfficeQACalibrationReport:
    return OfficeQACalibrationReport(
        runtime=OfficeQARuntime(
            name=name,
            max_tool_turns=6,
            max_completion_tokens=4096,
        ),
        n_tasks=30,
        score=score,
        parseable_answer_rate=parsed,
        systemic_failure_rate=systemic,
        oracle_parsed_pages_rate=1.0,
        eligible_count=eligible,
        failure_category_counts={},
    )


def test_selects_first_runtime_that_passes_all_gates() -> None:
    reports = [
        _report("oracle-6x4096", score=0.20, parsed=0.90, systemic=0.0, eligible=20),
        _report("oracle-12x4096", score=0.40, parsed=0.90, systemic=0.0, eligible=18),
        _report("oracle-24x8192", score=0.55, parsed=0.95, systemic=0.0, eligible=20),
    ]

    assert select_runtime(reports).runtime.name == "oracle-12x4096"


def test_no_runtime_passes_when_calibration_remains_floor() -> None:
    reports = [
        _report("a", score=0.10, parsed=0.9, systemic=0.0, eligible=20),
        _report("b", score=0.20, parsed=0.9, systemic=0.0, eligible=20),
    ]

    assert select_runtime(reports) is None


def _rows(count: int = 90) -> list[dict[str, object]]:
    rows = []
    for index in range(count):
        source_count = (index % 5) + 1
        rows.append(
            {
                "uid": f"UID{index:04d}",
                "question": f"Treasury-only question {index}",
                "difficulty": "hard" if index % 2 else "easy",
                "source_files": "\r\n".join(
                    f"treasury_{index}_{part}.txt" for part in range(source_count)
                ),
            }
        )
    return rows


def test_calibration_ids_are_deterministic_and_stratified() -> None:
    rows = _rows()

    first = select_officeqa_calibration_ids(rows, size=30, seed=20260812)
    second = select_officeqa_calibration_ids(rows, size=30, seed=20260812)

    assert first == second
    assert len(first) == len(set(first)) == 30
    by_id = {str(row["uid"]): row for row in rows}
    strata = {officeqa_stratum(by_id[uid]) for uid in first}
    assert len(strata) == 6


def test_freeze_excludes_calibration_and_preserves_declared_sizes() -> None:
    rows = _rows()
    calibration_ids = select_officeqa_calibration_ids(
        rows, size=30, seed=20260812
    )

    split = freeze_officeqa_pilot(rows, calibration_ids, seed=20260812)

    assert len(split.evolution) == 12
    assert len(split.validation) == 6
    assert len(split.test) == 20
    assert not set(calibration_ids) & set(split.all_ids)
    assert len(split.all_ids) == len(set(split.all_ids)) == 38
    assert set(split.evidence_eligibility) >= set(split.all_ids)


def test_freeze_rejects_insufficient_eligible_rows() -> None:
    rows = _rows(35)
    calibration_ids = select_officeqa_calibration_ids(rows, size=30, seed=7)

    with pytest.raises(ValueError, match="eligible"):
        freeze_officeqa_pilot(rows, calibration_ids, seed=7)


@pytest.mark.parametrize(
    ("question", "eligible", "reason"),
    [
        ("Compute the total from the Treasury Bulletin table.", True, "oracle_local"),
        (
            "Adjust the value using the BLS CPI-U annual average.",
            False,
            "external_evidence_required",
        ),
        (
            "Convert it using the Macrotrends exchange rate.",
            False,
            "external_evidence_required",
        ),
    ],
)
def test_evidence_eligibility_is_question_rule_based(
    question: str, eligible: bool, reason: str
) -> None:
    result = officeqa_evidence_eligibility({"uid": "u", "question": question})

    assert result.eligible is eligible
    assert result.reason == reason
