import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_contracts import (
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
)
from rsebench.evolution.skillopt_executor import SkillOptBudget
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


def _manifest(tmp_path: Path, benchmark: str) -> Path:
    budget = EXPECTED[benchmark]
    domain = "spreadsheet" if benchmark == "spreadsheetbench_verified" else "document"
    split = CleanEvolutionSplitManifest(
        benchmark=benchmark,
        domain=domain,
        seed=7,
        source_hash="a" * 64,
        train=[_task("train", benchmark)],
        validation=[_task("validation", benchmark)],
        clean_test=[_task("test", benchmark)],
        metadata={
            "runtime": {
                "max_steps": budget.max_steps,
                "batch_size": budget.batch_size,
                "workers": budget.workers,
                "max_tool_turns": budget.max_turns,
                "max_completion_tokens": budget.max_completion_tokens,
            }
        },
    )
    path = tmp_path / f"{benchmark}.json"
    path.write_text(split.model_dump_json(indent=2), encoding="utf-8")
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
    seed_relative = run_clean_skillopt._SEEDS[benchmark]
    seed = methods / seed_relative
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


def test_clean_skillopt_cli_has_no_seed_gate_or_noise_stage() -> None:
    parser = run_clean_skillopt.build_parser()
    destinations = {action.dest for action in parser._actions}

    assert destinations == {
        "help",
        "manifest",
        "method_seed",
        "output_root",
    }


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
