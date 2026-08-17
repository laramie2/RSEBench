from __future__ import annotations

from pathlib import Path

from rsebench.providers.deepseek import DeepSeekClient
from rsebench.validation.service import preflight_validation


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "configs/validation/validation-v1.yaml"


def test_validation_preflight_expands_16_without_provider_calls(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        del args, kwargs
        raise AssertionError("validation preflight must not call a provider")

    monkeypatch.setattr(DeepSeekClient, "complete", forbidden)

    report = preflight_validation(MATRIX)

    assert report["cell_count"] == 16
    assert report["provider_calls"] == 0
    assert report["ready_cell_count"] == 16
    assert report["domains"] == [
        "spreadsheet",
        "document",
        "interactive",
        "skill",
    ]
    assert report["stages"] == ["N1", "N2", "N3", "N4"]
    assert report["release_patch_replay"] == {
        "skilladaptor-webshop-validation-v1": "passed",
        "skillflow-validation-v1": "passed",
        "skillopt-officeqa-validation-v1": "passed",
        "skillopt-spreadsheet-validation-v1": "passed",
    }
