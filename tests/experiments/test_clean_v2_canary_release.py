from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    PROJECT_ROOT
    / "releases/diagnostic/clean-v2-canaries/manifest.json"
)


def test_clean_v2_canary_release_is_portable_complete_and_nonformal() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "rsebench.clean-canary-diagnostic.v1"
    assert payload["track"] == "diagnostic"
    assert payload["qualification_version"] == "clean-qualification-v2"
    assert payload["formal_qualification"] is False
    assert payload["all_canaries_passed"] is True
    assert set(payload["cells"]) == {
        "officeqa-skillopt",
        "skilllearn-offer-letter",
        "spreadsheet-skillopt",
        "webshop-skilladaptor",
    }
    assert all(
        cell["qualification"]["passed"] is True
        for cell in payload["cells"].values()
    )
    assert payload["selected_token_usage"] == {
        "attempted_calls": 6298,
        "billed_tokens": {
            "completion_tokens": 1167351,
            "prompt_tokens": 13005056,
            "total_tokens": 14172407,
        },
        "failed_calls": 0,
        "observed_coverage": 1.0,
    }
    assert payload["all_attempt_token_usage"] == {
        "attempted_calls": 7291,
        "billed_tokens": {
            "completion_tokens": 1649144,
            "prompt_tokens": 24500693,
            "total_tokens": 26149837,
        },
        "failed_calls": 0,
        "observed_coverage": 1.0,
    }
    assert payload["timing_contract"] == {
        "levels": ["run", "stage", "task"],
        "task_records_preserved_in_source_results": True,
    }
    assert "/home/" not in json.dumps(payload, sort_keys=True)
