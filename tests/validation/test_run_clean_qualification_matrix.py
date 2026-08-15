import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from rsebench.experiments.preflight import load_experiment_matrix
from scripts import run_clean_qualification_matrix as matrix


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / "configs/validation/clean_qualification_v1.yaml"
CANDIDATE_2_CONFIG = (
    PROJECT_ROOT / "configs/experiments/noise-screen-v1-candidate2.yaml"
)
CANDIDATE_3_CONFIG = (
    PROJECT_ROOT / "configs/experiments/noise-screen-v1-candidate3.yaml"
)
REUSE_FALLBACK_CONFIG = (
    PROJECT_ROOT / "configs/experiments/noise-screen-v1-reuse-fallback.yaml"
)


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


def test_candidate_matrices_expand_exact_preregistered_unit_counts() -> None:
    expected = {
        CANDIDATE_2_CONFIG: {
            "spreadsheetbench_verified": 3,
            "officeqa_full": 3,
            "webshop": 3,
            "skilllearnbench": 12,
        },
        CANDIDATE_3_CONFIG: {
            "spreadsheetbench_verified": 3,
            "officeqa_full": 3,
            "webshop": 3,
        },
        REUSE_FALLBACK_CONFIG: {
            "officeqa_full": 3,
            "webshop": 3,
        },
    }

    for path, counts in expected.items():
        config = matrix.load_config(path)
        formal = load_experiment_matrix(path)
        units = matrix.expand_units(config)
        assert Counter(unit.benchmark for unit in units) == counts
        assert len(units) == sum(counts.values())
        assert formal.candidate_index == config["candidate_index"]
        assert all(cell.manifest_candidate_index is not None for cell in formal.cells)


def test_matrix_uses_declared_skilllearn_manifests() -> None:
    config = matrix.load_config(CANDIDATE_2_CONFIG)
    formal = load_experiment_matrix(CANDIDATE_2_CONFIG)
    units = matrix.expand_units(config)
    skilllearn = [row for row in units if row.benchmark == "skilllearnbench"]

    assert formal.candidate_index == config["candidate_index"] == 2
    assert len(units) == 21
    assert len(skilllearn) == 12
    assert all(
        "noise_screen_v1/candidates/skilllearnbench" in " ".join(row.command)
        for row in skilllearn
    )
    assert all(row.mutable_resource_keys for row in skilllearn)
    assert len({row.command[row.command.index("--manifest") + 1] for row in skilllearn}) == 1
    assert {
        row.command[row.command.index("--family") + 1] for row in skilllearn
    } == {
        "organize-messy-files",
        "offer-letter-generator",
        "schedule-planning",
        "dependency-vulnerability-check",
    }


def test_candidate_matrix_default_dry_run_uses_formal_config_without_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("candidate dry run must not call subprocess or provider")

    monkeypatch.setattr(matrix.subprocess, "run", forbidden)

    result = matrix.run_matrix(
        CANDIDATE_2_CONFIG,
        execute=False,
        output_root=tmp_path,
    )

    assert len(result) == 21
    assert calls == []
    assert not (tmp_path / "matrix_status.json").exists()


def test_noise_screen_execute_requires_selection_gate_before_worktree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def forbidden() -> str:
        raise AssertionError("missing selection gate reached clean-worktree boundary")

    monkeypatch.setattr(matrix, "_ensure_clean_worktree", forbidden)

    with pytest.raises(
        ValueError,
        match="noise-screen execution requires selection_status and required_action",
    ):
        matrix.run_matrix(
            CANDIDATE_2_CONFIG,
            execute=True,
            output_root=tmp_path / "runs",
        )


def _selection_status(tmp_path: Path, actions: dict[str, str]) -> Path:
    path = tmp_path / "selection_status.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "rsebench.selection-status.v1",
                "domains": {
                    benchmark: {
                        "benchmark": benchmark,
                        "next_action": action,
                    }
                    for benchmark, action in actions.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_status_filter_starts_only_requested_candidate_cells(tmp_path: Path) -> None:
    config = matrix.load_config(CANDIDATE_2_CONFIG)
    status = _selection_status(
        tmp_path,
        {
            "spreadsheetbench_verified": "freeze_candidate",
            "officeqa_full": "run_candidate_2",
            "webshop": "freeze_candidate",
            "skilllearnbench": "freeze_candidate",
        },
    )

    selected = matrix.select_units_from_status(
        matrix.expand_units(config),
        status_path=status,
        required_action="run_candidate_2",
        matrix_candidate_index=2,
    )

    assert {row.benchmark for row in selected} == {"officeqa_full"}
    assert len(selected) == 3


def test_clean_matrix_runnable_action_mapping_is_exact() -> None:
    assert matrix.CLEAN_MATRIX_RUNNABLE_ACTIONS == {
        "rerun_candidate_1": 1,
        "run_candidate_2": 2,
        "run_candidate_3": 3,
    }


@pytest.mark.parametrize(
    ("actions", "required_action", "message"),
    [
        (
            {"officeqa_full": "run_candidate_2"},
            "run_candidate_3",
            "selection action differs from matrix candidate index",
        ),
        (
            {"unknown": "run_candidate_2"},
            "run_candidate_2",
            "selection status contains unknown matrix domains",
        ),
        (
            {"officeqa_full": "freeze_candidate"},
            "run_candidate_2",
            "no units request action run_candidate_2",
        ),
    ],
)
def test_status_filter_fails_closed_before_execution(
    monkeypatch,
    tmp_path: Path,
    actions: dict[str, str],
    required_action: str,
    message: str,
) -> None:
    status = _selection_status(tmp_path, actions)

    def forbidden() -> str:
        raise AssertionError("invalid selection must fail before execution preflight")

    monkeypatch.setattr(matrix, "_ensure_clean_worktree", forbidden)

    with pytest.raises(ValueError, match=message):
        matrix.run_matrix(
            CANDIDATE_2_CONFIG,
            execute=True,
            output_root=tmp_path / "runs",
            selection_status=status,
            required_action=required_action,
        )


def test_status_filter_rejects_unknown_typed_action(tmp_path: Path) -> None:
    config = matrix.load_config(CANDIDATE_2_CONFIG)
    status = _selection_status(tmp_path, {"officeqa_full": "launch_everything"})

    with pytest.raises(ValueError, match="next_action"):
        matrix.select_units_from_status(
            matrix.expand_units(config),
            status_path=status,
            required_action="run_candidate_2",
            matrix_candidate_index=2,
        )


@pytest.mark.parametrize(
    "required_action",
    [
        "replay_candidate_1",
        "freeze_candidate",
        "extend_replay_to_5",
        "clean_blocked_after_three_candidates",
        "clean_blocked_skilllearn_families",
    ],
)
def test_noise_screen_execute_rejects_nonrunnable_action_before_worktree(
    monkeypatch,
    tmp_path: Path,
    required_action: str,
) -> None:
    status = _selection_status(tmp_path, {"officeqa_full": required_action})

    def forbidden() -> str:
        raise AssertionError("nonrunnable action reached clean-worktree boundary")

    monkeypatch.setattr(matrix, "_ensure_clean_worktree", forbidden)

    with pytest.raises(ValueError, match="required action is not runnable"):
        matrix.run_matrix(
            CANDIDATE_2_CONFIG,
            execute=True,
            output_root=tmp_path / "runs",
            selection_status=status,
            required_action=required_action,
        )


def test_status_filter_rejects_domain_key_row_benchmark_mismatch(
    tmp_path: Path,
) -> None:
    status = tmp_path / "selection_status.json"
    status.write_text(
        json.dumps(
            {
                "schema_version": "rsebench.selection-status.v1",
                "domains": {
                    "officeqa_full": {
                        "benchmark": "webshop",
                        "next_action": "run_candidate_2",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="domain key must equal row benchmark"):
        matrix.select_units_from_status(
            matrix.expand_units(matrix.load_config(CANDIDATE_2_CONFIG)),
            status_path=status,
            required_action="run_candidate_2",
            matrix_candidate_index=2,
        )


def test_filtered_formal_matrix_resume_does_not_duplicate_completed_units(
    monkeypatch,
    tmp_path: Path,
) -> None:
    status = _selection_status(
        tmp_path,
        {
            "spreadsheetbench_verified": "freeze_candidate",
            "officeqa_full": "run_candidate_2",
            "webshop": "freeze_candidate",
            "skilllearnbench": "freeze_candidate",
        },
    )
    monkeypatch.setattr(matrix, "_ensure_clean_worktree", lambda: "commit")
    expanded = matrix.expand_units(
        matrix.load_config(CANDIDATE_2_CONFIG),
        output_root=tmp_path / "runs",
    )

    def fake_preflight(path, *, require_clean_worktree):
        assert path == CANDIDATE_2_CONFIG
        assert require_clean_worktree is False
        return SimpleNamespace(
            repository_commit="commit",
            units=[
                SimpleNamespace(
                    key=unit.key,
                    scheduled=unit.scheduled(tmp_path / "runs"),
                )
                for unit in expanded
            ],
        )

    monkeypatch.setattr(matrix, "preflight_matrix", fake_preflight)
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

    for _ in range(2):
        units = matrix.run_matrix(
            CANDIDATE_2_CONFIG,
            execute=True,
            output_root=tmp_path / "runs",
            selection_status=status,
            required_action="run_candidate_2",
            command_runner=fake_run,
        )

    assert len(units) == 3
    assert len(calls) == 3
    scheduler_status = json.loads(
        (tmp_path / "runs/candidate-2/matrix_status.json").read_text()
    )
    assert scheduler_status["metadata"]["expected_units"] == 21
    assert all(row["state"] == "completed" for row in scheduler_status["units"].values())


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
