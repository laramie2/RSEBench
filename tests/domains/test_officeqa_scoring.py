from __future__ import annotations

import pytest

from rsebench.domains.officeqa_scoring import (
    classify_officeqa_failure,
    score_officeqa,
    score_officeqa_details,
)


@pytest.mark.parametrize(
    ("gold", "prediction", "expected"),
    [
        ("56117.5", "55,991.4 million dollars", 1.0),
        ("264.632", "628.855", 0.0),
        ("-0.63", "-0.630", 1.0),
        ("March 3, 1977", "March 3, 1977", 1.0),
        ("March 3, 1977", "April 3, 1977", 0.0),
        ("[0.096, −184.143]", "[0.096, -184.143]", 1.0),
        ("[0.012, surplus]", "[0.012, surplus]", 1.0),
        ("[8, 152260]", "[8,152,260]", 1.0),
    ],
)
def test_officeqa_one_percent_score(gold: str, prediction: str, expected: float):
    assert score_officeqa(gold, prediction, tolerance=0.01) == expected


def test_score_details_keep_exact_match_as_a_diagnostic():
    result = score_officeqa_details(
        "56117.5", "55,991.4 million dollars", tolerance=0.01
    )

    assert result.hard == 1.0
    assert result.exact == 0.0
    assert result.predicted_answer == "55,991.4 million dollars"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "hard_score": 0.0,
                "predicted_answer": "",
                "fail_reason": "",
                "oracle_parsed_pages_included": False,
                "expects_oracle_pages": True,
            },
            "missing_oracle_page",
        ),
        (
            {
                "hard_score": 0.0,
                "predicted_answer": "",
                "fail_reason": "search is disabled",
                "oracle_parsed_pages_included": True,
                "external_evidence_required": True,
            },
            "external_evidence_required",
        ),
        (
            {
                "hard_score": 0.0,
                "predicted_answer": "",
                "fail_reason": "Exceeded tool-turn budget (12)",
                "oracle_parsed_pages_included": True,
            },
            "tool_budget_exhausted",
        ),
        (
            {
                "hard_score": 0.0,
                "predicted_answer": "",
                "fail_reason": "Model did not produce a final answer",
                "oracle_parsed_pages_included": True,
            },
            "answer_missing",
        ),
        (
            {
                "hard_score": 0.0,
                "predicted_answer": "",
                "fail_reason": "error: APIError: provider unavailable",
                "oracle_parsed_pages_included": True,
            },
            "provider_failure",
        ),
        (
            {
                "hard_score": 0.0,
                "predicted_answer": "wrong",
                "fail_reason": "predicted wrong",
                "oracle_parsed_pages_included": True,
            },
            "incorrect_answer",
        ),
        (
            {
                "hard_score": 1.0,
                "predicted_answer": "42",
                "fail_reason": "",
                "oracle_parsed_pages_included": True,
            },
            "correct",
        ),
    ],
)
def test_officeqa_failure_taxonomy(kwargs: dict[str, object], expected: str):
    assert classify_officeqa_failure(**kwargs) == expected
