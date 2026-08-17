from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rsebench.cli import app
from rsebench.providers.deepseek import DeepSeekClient


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "configs/validation/validation-v1.yaml"
RUNNER = CliRunner()


def test_validation_preflight_cli_reports_exact_matrix() -> None:
    result = RUNNER.invoke(
        app,
        ["validation", "preflight", "--matrix", str(MATRIX)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["cell_count"] == 16
    assert payload["provider_calls"] == 0


def test_validation_run_requires_explicit_cost_confirmation() -> None:
    result = RUNNER.invoke(
        app,
        ["validation", "run", "--matrix", str(MATRIX)],
    )

    assert result.exit_code != 0
    assert "confirm-provider-cost" in result.output


def test_confirmed_run_still_refuses_interface_only_operators(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        del args, kwargs
        raise AssertionError("interface-only run must not call a provider")

    monkeypatch.setattr(DeepSeekClient, "complete", forbidden)
    result = RUNNER.invoke(
        app,
        [
            "validation",
            "run",
            "--matrix",
            str(MATRIX),
            "--confirm-provider-cost",
        ],
    )

    assert result.exit_code != 0
    assert "interface-only" in result.output


def test_validation_status_preserves_fixed_pending_denominator(tmp_path: Path) -> None:
    result = RUNNER.invoke(
        app,
        [
            "validation",
            "status",
            "--matrix",
            str(MATRIX),
            "--run-root",
            str(tmp_path / "not-started"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["cell_count"] == 16
    assert payload["states"] == {"pending": 16}
