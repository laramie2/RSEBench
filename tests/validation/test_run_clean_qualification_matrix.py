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


def test_matrix_execute_is_sequential_and_persists_each_terminal_unit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    raw = CONFIG.read_text(encoding="utf-8").replace(
        "method_seeds: [20260813, 20260814, 20260815]",
        "method_seeds: [20260813]",
    )
    config_path.write_text(raw, encoding="utf-8")
    observed_status_lengths = []
    monkeypatch.setattr(matrix, "_ensure_clean_worktree", lambda: "commit")

    def fake_run(command, **kwargs):
        status_path = tmp_path / "matrix_status.json"
        if status_path.exists():
            observed_status_lengths.append(
                len(json.loads(status_path.read_text())["units"])
            )
        else:
            observed_status_lengths.append(0)
        run_dir = tmp_path / f"run-{len(observed_status_lengths)}"
        run_dir.mkdir()
        (run_dir / "result.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=f"{run_dir}\n", stderr="")

    monkeypatch.setattr(matrix.subprocess, "run", fake_run)

    units = matrix.run_matrix(config_path, execute=True, output_root=tmp_path)

    assert len(units) == 11
    assert observed_status_lengths == list(range(11))
    status = json.loads((tmp_path / "matrix_status.json").read_text())
    assert status["terminal_units"] == 11
    assert all(row["status"] == "completed" for row in status["units"])


def test_matrix_refuses_resume_under_changed_config_hash(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(matrix, "_ensure_clean_worktree", lambda: "commit")
    (tmp_path / "matrix_status.json").write_text(
        json.dumps({"config_hash": "0" * 64, "units": [{"status": "completed"}]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="config hash differs"):
        matrix.run_matrix(CONFIG, execute=True, output_root=tmp_path)
