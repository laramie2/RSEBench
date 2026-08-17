from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

from rsebench.experiments.scheduler import ExperimentScheduler, UnitState
from rsebench.validation import load_and_expand
from rsebench.validation.scheduler import build_validation_units


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "configs/validation/validation-v1.yaml"


def _method_sources(project: Path) -> None:
    for method in ("skillopt", "skilladaptor", "skillflow"):
        source = project / f"methods/validated/{method}/source"
        source.mkdir(parents=True)
        (source / "method.py").write_text(f"METHOD = {method!r}\n", encoding="utf-8")


def test_all_sixteen_cells_run_concurrently_with_isolated_attempt_paths(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _method_sources(project)
    cells = load_and_expand(MATRIX)
    units = build_validation_units(
        cells,
        tmp_path / "run",
        project_root=project,
    )
    patch_counts = {
        unit.key: len(unit.patch_paths)
        for unit in units
        if "spreadsheet" in unit.key or "document" in unit.key
    }
    assert set(patch_counts.values()) == {4, 5}
    units = tuple(
        unit.model_copy(update={"source_revision": None, "patch_paths": []})
        for unit in units
    )
    barrier = threading.Barrier(16, timeout=5)
    lock = threading.Lock()
    active = 0
    peak = 0
    environments: list[dict[str, str]] = []

    def fake_runner(command, *, cwd, env, unit):
        nonlocal active, peak
        del cwd
        with lock:
            active += 1
            peak = max(peak, active)
            environments.append(env)
        barrier.wait()
        output_root = Path(command[command.index("--output-root") + 1])
        result_root = output_root / "result"
        result_root.mkdir(parents=True)
        (result_root / "result.json").write_text(
            json.dumps({"identity": {"experiment_id": unit.experiment_id}}),
            encoding="utf-8",
        )
        with lock:
            active -= 1
        return SimpleNamespace(returncode=0, stdout=f"{result_root}\n", stderr="")

    scheduler = ExperimentScheduler(
        run_root=tmp_path / "run",
        project_root=project,
        max_parallel=16,
        command_runner=fake_runner,
    )
    rows = scheduler.run(units)

    assert len(units) == 16
    assert peak == 16
    assert all(row["state"] == UnitState.completed.value for row in rows)
    for variable in (
        "TMPDIR",
        "XDG_CACHE_HOME",
        "RSEBENCH_OUTPUT_ROOT",
        "RSEBENCH_WORKSPACE_ROOT",
        "RSEBENCH_NOISY_ROOT",
        "RSEBENCH_MUTATION_AUDIT_ROOT",
    ):
        assert len({environment[variable] for environment in environments}) == 16
    copied_sources = {
        environment["RSEBENCH_METHOD_SOURCE"]
        for environment in environments
        if environment["RSEBENCH_SOURCE_MODE"] == "copy_on_run"
    }
    assert len(copied_sources) == 16
    assert all(not unit.mutable_resource_keys for unit in units)


def test_read_only_source_change_marks_only_that_cell_invalid(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _method_sources(project)
    cell = next(
        cell
        for cell in load_and_expand(MATRIX)
        if cell.domain == "spreadsheet" and cell.stage == "N1"
    )
    unit = build_validation_units(
        (cell,),
        tmp_path / "run",
        project_root=project,
    )[0].model_copy(
        update={
            "source_mode": "read_only",
            "source_revision": None,
            "patch_paths": [],
        }
    )

    def mutating_runner(command, *, cwd, env, unit):
        del cwd
        Path(env["RSEBENCH_METHOD_SOURCE"], "unexpected.txt").write_text(
            "mutation", encoding="utf-8"
        )
        output_root = Path(command[command.index("--output-root") + 1])
        result_root = output_root / "result"
        result_root.mkdir(parents=True)
        (result_root / "result.json").write_text(
            json.dumps({"identity": {"experiment_id": unit.experiment_id}}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=f"{result_root}\n", stderr="")

    rows = ExperimentScheduler(
        run_root=tmp_path / "run",
        project_root=project,
        max_parallel=1,
        command_runner=mutating_runner,
    ).run((unit,))

    assert rows[0]["state"] == UnitState.invalid.value
    assert "read-only method source changed" in rows[0]["attempts"][-1]["error"]


def test_copy_on_run_replays_release_patch_from_upstream_revision(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    source = project / "methods/validated/fixture/source"
    source.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Test"], check=True
    )
    value = source / "value.txt"
    value.write_text("upstream\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "value.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "commit", "-q", "-m", "upstream"],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    value.write_text("patched\n", encoding="utf-8")
    patch = project / "methods/validated/fixture/patches/fix.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text(
        subprocess.run(
            ["git", "-C", str(source), "diff", "--binary"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout,
        encoding="utf-8",
    )
    value.write_text("dirty-current-checkout\n", encoding="utf-8")

    from rsebench.experiments.scheduler import ScheduledUnit

    unit = ScheduledUnit(
        key="fixture",
        experiment_id="a" * 64,
        command=["fake"],
        output_dir="unused",
        adapter_key="fixture",
        source_dir=str(source),
        source_mode="copy_on_run",
        source_revision=revision,
        patch_paths=[str(patch)],
    )

    def fake_runner(command, *, cwd, env, unit):
        del cwd
        assert Path(env["RSEBENCH_METHOD_SOURCE"], "value.txt").read_text() == (
            "patched\n"
        )
        output_root = Path(command[command.index("--output-root") + 1])
        result_root = output_root / "result"
        result_root.mkdir(parents=True)
        (result_root / "result.json").write_text(
            json.dumps({"identity": {"experiment_id": unit.experiment_id}}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=f"{result_root}\n", stderr="")

    rows = ExperimentScheduler(
        run_root=tmp_path / "run-release-copy",
        project_root=project,
        max_parallel=1,
        command_runner=fake_runner,
    ).run((unit,))

    assert rows[0]["state"] == UnitState.completed.value
    assert value.read_text(encoding="utf-8") == "dirty-current-checkout\n"
