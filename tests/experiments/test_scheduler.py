from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from rsebench.experiments.scheduler import (
    ExperimentScheduler,
    ScheduledUnit,
    UnitState,
)


def _unit(
    key: str,
    *,
    adapter: str,
    mutable: list[str] | None = None,
    fail: bool = False,
) -> ScheduledUnit:
    return ScheduledUnit(
        key=key,
        experiment_id=(key.encode().hex() + "0" * 64)[:64],
        command=["fake", "--fail" if fail else "--ok", "--output-root", "unused"],
        output_dir="unused",
        mutable_resource_keys=mutable or [],
        adapter_key=adapter,
        adapter_max_parallel=2,
    )


def test_scheduler_allows_readonly_overlap_serializes_mutable_and_isolates_failure(
    tmp_path: Path,
) -> None:
    lock = threading.Lock()
    active_by_adapter: dict[str, int] = {}
    active_mutable: dict[str, int] = {}
    peaks: dict[str, int] = {}
    environments: list[dict[str, str]] = []

    def fake_runner(command, *, cwd, env, unit):
        del cwd
        with lock:
            environments.append(env)
            active_by_adapter[unit.adapter_key] = (
                active_by_adapter.get(unit.adapter_key, 0) + 1
            )
            peaks[unit.adapter_key] = max(
                peaks.get(unit.adapter_key, 0), active_by_adapter[unit.adapter_key]
            )
            for resource in unit.mutable_resource_keys:
                active_mutable[resource] = active_mutable.get(resource, 0) + 1
                peaks[resource] = max(peaks.get(resource, 0), active_mutable[resource])
        time.sleep(0.05)
        output_root = Path(command[command.index("--output-root") + 1])
        run_dir = output_root / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(
            json.dumps({"identity": {"experiment_id": unit.experiment_id}}),
            encoding="utf-8",
        )
        with lock:
            active_by_adapter[unit.adapter_key] -= 1
            for resource in unit.mutable_resource_keys:
                active_mutable[resource] -= 1
        failed = "--fail" in command
        return SimpleNamespace(
            returncode=1 if failed else 0,
            stdout=f"{run_dir}\n" if not failed else "",
            stderr="fixture failure" if failed else "",
        )

    units = [
        _unit("spreadsheet", adapter="skillopt"),
        _unit("officeqa", adapter="skillopt", fail=True),
        _unit(
            "skilllearn-a",
            adapter="skilllearn",
            mutable=["docker:skilllearn-family"],
        ),
        _unit(
            "skilllearn-b",
            adapter="skilllearn",
            mutable=["docker:skilllearn-family"],
        ),
    ]
    scheduler = ExperimentScheduler(
        run_root=tmp_path,
        project_root=tmp_path,
        max_parallel=4,
        command_runner=fake_runner,
    )

    rows = scheduler.run(units)

    assert peaks["skillopt"] == 2
    assert peaks["docker:skilllearn-family"] == 1
    states = {row["key"]: row["state"] for row in rows}
    assert states == {
        "spreadsheet": UnitState.completed.value,
        "officeqa": UnitState.failed.value,
        "skilllearn-a": UnitState.completed.value,
        "skilllearn-b": UnitState.completed.value,
    }
    assert len({env["TMPDIR"] for env in environments}) == 4
    assert all(env["PYTHONPATH"] == str(tmp_path / "src") for env in environments)
    assert (tmp_path / "matrix_status.json").is_file()
    assert (tmp_path / "events.jsonl").is_file()


def test_scheduler_resume_requires_matching_identity_and_result(tmp_path: Path) -> None:
    calls = []

    def fake_runner(command, *, cwd, env, unit):
        del cwd, env
        calls.append(unit.experiment_id)
        output_root = Path(command[command.index("--output-root") + 1])
        run_dir = output_root / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(
            json.dumps({"identity": {"experiment_id": unit.experiment_id}}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=f"{run_dir}\n", stderr="")

    scheduler = ExperimentScheduler(
        run_root=tmp_path,
        project_root=tmp_path,
        max_parallel=1,
        command_runner=fake_runner,
    )
    first = _unit("spreadsheet", adapter="skillopt")

    scheduler.run([first])
    scheduler.run([first])
    changed = first.model_copy(update={"experiment_id": "f" * 64})
    scheduler.run([changed])

    assert calls == [first.experiment_id, "f" * 64]
    status = json.loads((tmp_path / "matrix_status.json").read_text())
    assert len(status["units"]["spreadsheet"]["attempts"]) == 2


def test_scheduler_preserves_pending_rows_when_new_work_is_bounded(
    tmp_path: Path,
) -> None:
    def fake_runner(command, *, cwd, env, unit):
        del cwd, env
        output_root = Path(command[command.index("--output-root") + 1])
        run_dir = output_root / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(
            json.dumps({"identity": {"experiment_id": unit.experiment_id}}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=f"{run_dir}\n", stderr="")

    scheduler = ExperimentScheduler(
        run_root=tmp_path,
        project_root=tmp_path,
        max_parallel=2,
        command_runner=fake_runner,
    )
    units = [
        _unit("spreadsheet", adapter="skillopt"),
        _unit("officeqa", adapter="skillopt"),
    ]

    rows = scheduler.run(units, max_new_units=1)

    assert [row["state"] for row in rows] == [
        UnitState.completed.value,
        UnitState.pending.value,
    ]


def test_scheduler_rejects_changed_resume_metadata(tmp_path: Path) -> None:
    ExperimentScheduler(
        run_root=tmp_path,
        project_root=tmp_path,
        max_parallel=1,
        status_metadata={"config_hash": "a" * 64, "git_head": "1" * 40},
    )

    try:
        ExperimentScheduler(
            run_root=tmp_path,
            project_root=tmp_path,
            max_parallel=1,
            status_metadata={"config_hash": "b" * 64, "git_head": "1" * 40},
        )
    except RuntimeError as exc:
        assert "config_hash differs" in str(exc)
    else:
        raise AssertionError("changed scheduler metadata must reject resume")
