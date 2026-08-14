import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from rsebench import cli


runner = CliRunner()


def test_experiment_preflight_prints_zero_calls_and_unit_identities(
    monkeypatch,
    tmp_path: Path,
) -> None:
    matrix = tmp_path / "matrix.yaml"
    matrix.write_text("fixture: true\n", encoding="utf-8")
    identities = ["a" * 64, "b" * 64]
    report = SimpleNamespace(
        provider_calls=0,
        all_ready=True,
        units=[
            SimpleNamespace(
                key=f"unit-{index}",
                identity=SimpleNamespace(experiment_id=experiment_id),
            )
            for index, experiment_id in enumerate(identities)
        ],
    )
    monkeypatch.setattr(cli, "preflight_matrix", lambda *args, **kwargs: report)

    result = runner.invoke(
        cli.app,
        ["experiment", "preflight", "--matrix", str(matrix)],
    )

    assert result.exit_code == 0
    assert "provider_calls=0" in result.stdout
    assert all(experiment_id in result.stdout for experiment_id in identities)


def test_experiment_run_refuses_unconfirmed_provider_cost(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.yaml"
    matrix.write_text("fixture: true\n", encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["experiment", "run", "--matrix", str(matrix)],
    )

    assert result.exit_code == 2
    assert "--confirm-provider-cost" in result.stdout


def test_unified_subapps_expose_expected_commands() -> None:
    baseline_help = runner.invoke(cli.app, ["baselines", "--help"])
    experiment_help = runner.invoke(cli.app, ["experiment", "--help"])

    assert baseline_help.exit_code == 0
    assert {"bootstrap", "verify"} <= set(baseline_help.stdout.split())
    assert experiment_help.exit_code == 0
    assert {"preflight", "run", "status", "aggregate"} <= set(
        experiment_help.stdout.split()
    )
    release_help = runner.invoke(cli.app, ["release", "--help"])
    assert release_help.exit_code == 0
    assert "freeze" in release_help.stdout.split()


def test_experiment_aggregate_passes_matrix_contract_to_scheduler_aggregate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    matrix_path = tmp_path / "matrix.yaml"
    matrix_path.write_text("fixture: true\n", encoding="utf-8")
    run_root = tmp_path / "run"
    matrix_contract = SimpleNamespace(output_root=str(run_root))
    seen = {}

    monkeypatch.setattr(cli, "load_experiment_matrix", lambda path: matrix_contract)

    def fake_build_aggregate(root, *, matrix):
        seen.update(root=Path(root), matrix=matrix)
        return {"cells": {}}

    monkeypatch.setattr(
        "scripts.aggregate_clean_qualification.build_aggregate",
        fake_build_aggregate,
    )

    result = runner.invoke(
        cli.app,
        ["experiment", "aggregate", "--matrix", str(matrix_path)],
    )

    assert result.exit_code == 0
    assert seen == {"root": run_root, "matrix": matrix_contract}
    assert json.loads((run_root / "aggregate.json").read_text()) == {"cells": {}}
