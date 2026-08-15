import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import (
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
)
from rsebench.evolution.skillopt_executor import (
    SkillOptBudget,
    SkillOptExecutor as RealSkillOptExecutor,
)
from rsebench.selection import StableSplitCandidate
from scripts import run_clean_skillopt


EXPECTED = {
    "spreadsheetbench_verified": SkillOptBudget(
        max_steps=3,
        batch_size=7,
        workers=2,
        max_turns=3,
        max_completion_tokens=2048,
    ),
    "officeqa_full": SkillOptBudget(
        max_steps=3,
        batch_size=4,
        workers=2,
        max_turns=12,
        max_completion_tokens=4096,
    ),
}
EXPECTED_TASK_COUNTS = {
    "spreadsheetbench_verified": {
        "clean-qualification-v1": (20, 10, 30),
        "clean-qualification-v2": (20, 10, 30),
        "noise-screen-v1": (20, 10, 30),
    },
    "officeqa_full": {
        "clean-qualification-v1": (12, 6, 20),
        "clean-qualification-v2": (12, 12, 20),
        "noise-screen-v1": (12, 12, 20),
    },
}


def _task(task_id: str, benchmark: str) -> TaskManifest:
    domain = "spreadsheet" if benchmark == "spreadsheetbench_verified" else "document"
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain=domain,
        prompt=task_id,
        gold_answers=["x"],
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
    )


def _manifest(
    tmp_path: Path,
    benchmark: str,
    *,
    qualification_version: str | None = None,
    task_counts: tuple[int, int, int] | None = None,
) -> Path:
    budget = EXPECTED[benchmark]
    domain = "spreadsheet" if benchmark == "spreadsheetbench_verified" else "document"

    def task(task_id: str) -> TaskManifest:
        result = _task(task_id, benchmark)
        if benchmark == "spreadsheetbench_verified":
            workbook = tmp_path / f"workbooks/{task_id}/initial.xlsx"
            workbook.parent.mkdir(parents=True, exist_ok=True)
            workbook.write_bytes(b"workbook")
            result = result.model_copy(
                update={
                    "artifact_path": str(workbook),
                    "metadata": {
                        "answer_range": "A1",
                        "answer_sheet": "Sheet1",
                    },
                }
            )
        return result

    version = qualification_version or "clean-qualification-v1"
    train_count, validation_count, clean_test_count = (
        task_counts or EXPECTED_TASK_COUNTS[benchmark][version]
    )
    split = CleanEvolutionSplitManifest(
        benchmark=benchmark,
        domain=domain,
        seed=7,
        source_hash="a" * 64,
        train=[task(f"train-{index}") for index in range(train_count)],
        validation=[
            task(f"validation-{index}") for index in range(validation_count)
        ],
        clean_test=[task(f"test-{index}") for index in range(clean_test_count)],
        metadata={
            "runtime": {
                "max_steps": budget.max_steps,
                "batch_size": budget.batch_size,
                "workers": budget.workers,
                "max_tool_turns": budget.max_turns,
                "max_completion_tokens": budget.max_completion_tokens,
            },
            **(
                {"qualification_version": qualification_version}
                if qualification_version is not None
                else {}
            ),
        },
    )
    path = tmp_path / f"{benchmark}.json"
    path.write_text(split.model_dump_json(indent=2), encoding="utf-8")
    return path


def _candidate_manifest(
    tmp_path: Path,
    benchmark: str,
    *,
    task_counts: tuple[int, int, int] | None = None,
) -> Path:
    path = _manifest(
        tmp_path,
        benchmark,
        qualification_version="noise-screen-v1",
        task_counts=task_counts,
    )
    split = CleanEvolutionSplitManifest.model_validate_json(path.read_text())
    roles = {
        "train": split.train,
        "validation": split.validation,
        "qualification_test": split.clean_test,
        "screening_test": [_task("screening", benchmark)],
    }
    candidate = StableSplitCandidate(
        benchmark=split.benchmark,
        domain=split.domain,
        candidate_index=2,
        source_hash=canonical_hash("candidate"),
        selection_hash=canonical_hash("selection"),
        metadata={
            **split.metadata,
            "selection_version": "noise-screen-v1",
            "source_seed": split.seed,
            "baseline": "skillopt",
        },
        **roles,
    )
    path.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")
    return path


@pytest.mark.parametrize("benchmark", list(EXPECTED))
def test_clean_skillopt_launcher_locks_budget_and_policy(
    tmp_path: Path,
    monkeypatch,
    benchmark: str,
) -> None:
    captured = {}
    expected_runtime = {
        "max_steps": EXPECTED[benchmark].max_steps,
        "batch_size": EXPECTED[benchmark].batch_size,
        "workers": EXPECTED[benchmark].workers,
        "max_tool_turns": EXPECTED[benchmark].max_turns,
        "max_completion_tokens": EXPECTED[benchmark].max_completion_tokens,
    }
    methods = tmp_path / "methods"
    method_root = methods / "skillopt"
    seed_relative = run_clean_skillopt._SEEDS[benchmark]
    seed = method_root / seed_relative
    seed.parent.mkdir(parents=True)
    seed.write_text("seed", encoding="utf-8")

    class FakeExecutor:
        def __init__(self, **kwargs):
            captured["executor"] = kwargs

    class FakeRunner:
        def __init__(self, executor):
            captured["runner_executor"] = executor

        def run(self, **kwargs):
            captured["run"] = kwargs
            run_dir = Path(kwargs["output_root"]) / "run-1"
            run_dir.mkdir(parents=True)
            return SimpleNamespace(run_dir=str(run_dir))

    monkeypatch.setattr(run_clean_skillopt, "SkillOptExecutor", FakeExecutor)
    monkeypatch.setattr(run_clean_skillopt, "CleanEvolutionRunner", FakeRunner)
    monkeypatch.setattr(run_clean_skillopt, "methods_root", lambda: methods)
    identity = object()
    attempt = object()
    monkeypatch.setattr(
        run_clean_skillopt,
        "load_runtime_identity",
        lambda **kwargs: (identity, attempt),
    )
    monkeypatch.setattr(
        run_clean_skillopt,
        "combined_method_env",
        lambda _: {"RSEBENCH_DATA_ROOT": str(tmp_path / "data")},
    )

    run_dir = run_clean_skillopt.run_manifest(
        _manifest(tmp_path, benchmark),
        method_seed=20260813,
        output_root=tmp_path / "runs",
    )

    assert run_dir.name == "run-1"
    assert captured["executor"]["budget"] == EXPECTED[benchmark]
    policy = captured["run"]["policy"]
    if benchmark == "officeqa_full":
        assert policy == CleanQualificationPolicy(
            min_parseable_answer_rate=0.80,
            max_systemic_failure_rate=0.05,
        )
    else:
        assert policy == CleanQualificationPolicy()
    assert captured["run"]["seed_skill_path"] == seed
    assert captured["run"]["output_root"] == (
        tmp_path / "runs" / benchmark / "20260813"
    )
    assert captured["run"]["parameters"]["runtime"] == expected_runtime
    assert captured["run"]["identity"] is identity
    assert captured["run"]["attempt"] is attempt
    assert captured["run"]["parameters"]["qualification_version"] == (
        "clean-qualification-v1"
    )


def test_clean_skillopt_cli_has_no_seed_gate_or_noise_stage() -> None:
    parser = run_clean_skillopt.build_parser()
    destinations = {action.dest for action in parser._actions}

    assert destinations == {
        "help",
        "manifest",
        "method_seed",
        "output_root",
        "dry_run",
    }


def test_noise_screen_skillopt_requires_runtime_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}

    class IdentityBoundaryReached(Exception):
        pass

    def capture(**kwargs):
        captured.update(kwargs)
        raise IdentityBoundaryReached

    monkeypatch.setattr(run_clean_skillopt, "load_runtime_identity", capture)

    with pytest.raises(IdentityBoundaryReached):
        run_clean_skillopt.run_manifest(
            _candidate_manifest(tmp_path, "officeqa_full"),
            method_seed=20260813,
            output_root=tmp_path / "runs",
        )

    assert captured["required"] is True
    assert captured["benchmark"] == "officeqa_full"


@pytest.mark.parametrize(
    ("benchmark", "qualification_version", "task_counts"),
    [
        ("spreadsheetbench_verified", "noise-screen-v1", (19, 10, 30)),
        ("officeqa_full", None, (12, 12, 20)),
        ("officeqa_full", "clean-qualification-v2", (12, 6, 20)),
        ("officeqa_full", "noise-screen-v1", (12, 6, 20)),
    ],
)
def test_clean_skillopt_rejects_wrong_task_counts_before_runtime_identity(
    tmp_path: Path,
    monkeypatch,
    benchmark: str,
    qualification_version: str | None,
    task_counts: tuple[int, int, int],
) -> None:
    boundary_calls: list[str] = []

    def forbidden_identity(**kwargs):
        del kwargs
        boundary_calls.append("identity")
        raise AssertionError("wrong counts reached runtime identity boundary")

    monkeypatch.setattr(run_clean_skillopt, "load_runtime_identity", forbidden_identity)
    manifest = (
        _candidate_manifest(tmp_path, benchmark, task_counts=task_counts)
        if qualification_version == "noise-screen-v1"
        else _manifest(
            tmp_path,
            benchmark,
            qualification_version=qualification_version,
            task_counts=task_counts,
        )
    )

    with pytest.raises(ValueError, match="task counts differ from formal settings"):
        run_clean_skillopt.run_manifest(
            manifest,
            method_seed=20260813,
            output_root=tmp_path / "runs",
            dry_run=False,
        )

    assert boundary_calls == []


def test_clean_skillopt_launcher_rejects_runtime_drift(
    tmp_path: Path,
) -> None:
    path = _manifest(tmp_path, "officeqa_full")
    payload = CleanEvolutionSplitManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    payload.metadata["runtime"]["max_tool_turns"] = 3
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="runtime metadata differs"):
        run_clean_skillopt.run_manifest(
            path,
            method_seed=20260813,
            output_root=tmp_path / "runs",
        )


def test_clean_skillopt_dry_run_renders_only_clean_native_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    methods = tmp_path / "methods"
    method_root = methods / "skillopt"
    (method_root / ".venv/bin").mkdir(parents=True)
    (method_root / ".venv/bin/python").write_text("", encoding="utf-8")
    (method_root / "scripts").mkdir()
    (method_root / "scripts/train.py").write_text("", encoding="utf-8")
    config = method_root / "configs/spreadsheetbench/default.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("env: {name: spreadsheetbench}", encoding="utf-8")
    seed = method_root / run_clean_skillopt._SEEDS["spreadsheetbench_verified"]
    seed.parent.mkdir(parents=True)
    seed.write_text("seed", encoding="utf-8")

    def forbidden_command_runner(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("dry run must not invoke command runner")

    class CapturingExecutor(RealSkillOptExecutor):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, command_runner=forbidden_command_runner)

    monkeypatch.setattr(run_clean_skillopt, "SkillOptExecutor", CapturingExecutor)
    monkeypatch.setattr(run_clean_skillopt, "methods_root", lambda: methods)
    monkeypatch.setattr(
        run_clean_skillopt,
        "combined_method_env",
        lambda _: {"RSEBENCH_DATA_ROOT": str(tmp_path / "data")},
    )

    run_dir = run_clean_skillopt.run_manifest(
        _manifest(tmp_path, "spreadsheetbench_verified"),
        method_seed=20260813,
        output_root=tmp_path / "preflight",
        dry_run=True,
    )

    assert calls == []
    raw = (run_dir / "dry_run.json").read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload["arm_manifest"]["arm"] == "clean"
    assert payload["task_counts"] == {
        "train": 20,
        "validation": 10,
        "clean_test": 30,
    }
    assert "noisy" not in raw
    assert "--eval_test" in payload["native_command"]
    assert "false" in payload["native_command"]
    assert list(run_dir.rglob("*.jsonl")) == []
