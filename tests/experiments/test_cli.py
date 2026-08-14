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
