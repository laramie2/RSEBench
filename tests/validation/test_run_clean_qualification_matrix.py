import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_clean_qualification_matrix as matrix


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / "configs/validation/clean_qualification_v1.yaml"


def test_matrix_expands_exactly_33_clean_only_units() -> None:
    config = matrix.load_config(CONFIG)
    units = matrix.expand_units(config)

    assert len(units) == 33
    assert Counter(unit.benchmark for unit in units) == {
        "spreadsheetbench_verified": 3,
        "officeqa_full": 3,
        "webshop": 3,
        "skilllearnbench": 24,
    }
    assert {unit.method_seed for unit in units} == {20260813, 20260814, 20260815}
    assert all(len(unit.experiment_id) == 64 for unit in units)
    assert {
        unit.adapter_key for unit in units if unit.benchmark != "skilllearnbench"
    } == {"skillopt", "skilladaptor"}
    assert all(
        unit.mutable_resource_keys == [f"docker:skilllearn:{unit.family}"]
        for unit in units
        if unit.benchmark == "skilllearnbench"
    )
    assert all(
        "paired" not in " ".join(unit.command).casefold()
        and "n1" not in " ".join(unit.command).casefold()
        for unit in units
    )


def test_matrix_default_dry_run_makes_no_subprocess_call(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("dry run must not call subprocess")

    monkeypatch.setattr(matrix.subprocess, "run", forbidden)

    result = matrix.run_matrix(CONFIG, execute=False, output_root=tmp_path)

    assert len(result) == 33
    assert calls == []
    assert not (tmp_path / "matrix_status.json").exists()


def test_matrix_execute_delegates_all_units_to_isolated_scheduler(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    raw = CONFIG.read_text(encoding="utf-8").replace(
        "method_seeds: [20260813, 20260814, 20260815]",
        "method_seeds: [20260813]",
    )
    config_path.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(matrix, "_ensure_clean_worktree", lambda: "commit")
    calls = []

    def fake_run(command, *, cwd, env, unit):
        del cwd, env
        calls.append(unit.key)
        output_root = Path(command[command.index("--output-root") + 1])
        run_dir = output_root / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(
            json.dumps({"identity": {"experiment_id": unit.experiment_id}}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=f"{run_dir}\n", stderr="")

    units = matrix.run_matrix(
        config_path,
        execute=True,
        output_root=tmp_path,
        command_runner=fake_run,
        max_parallel=4,
    )

    assert len(units) == 11
    assert len(calls) == 11
    status = json.loads((tmp_path / "matrix_status.json").read_text())
    assert status["metadata"]["expected_units"] == 11
    assert status["metadata"]["git_head"] == "commit"
    assert all(row["state"] == "completed" for row in status["units"].values())


def test_matrix_refuses_resume_under_changed_config_hash(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(matrix, "_ensure_clean_worktree", lambda: "commit")
    (tmp_path / "matrix_status.json").write_text(
        json.dumps(
            {
                "schema_version": "rsebench.scheduler-status.v1",
                "metadata": {"config_hash": "0" * 64, "git_head": "commit"},
                "units": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="config hash differs"):
        matrix.run_matrix(CONFIG, execute=True, output_root=tmp_path)


def test_matrix_can_stage_a_bounded_number_of_new_units(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(matrix, "_ensure_clean_worktree", lambda: "commit")
    calls = []

    def fake_run(command, *, cwd, env, unit):
        del cwd, env
        calls.append(command)
        output_root = Path(command[command.index("--output-root") + 1])
        run_dir = output_root / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(
            json.dumps({"identity": {"experiment_id": unit.experiment_id}}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=f"{run_dir}\n", stderr="")

    matrix.run_matrix(
        CONFIG,
        execute=True,
        output_root=tmp_path,
        max_new_units=2,
        command_runner=fake_run,
    )

    status = json.loads((tmp_path / "matrix_status.json").read_text())
    assert len(calls) == 2
    assert len(status["units"]) == 2
    assert status["metadata"]["expected_units"] == 33
