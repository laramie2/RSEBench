import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_contracts import (
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
)
from scripts import run_clean_skilllearn


RUNTIME = {
    "max_tool_turns": 16,
    "max_completion_tokens": 4096,
    "evolution_rounds": 2,
    "require_prebuilt_images": True,
}


def _task(
    task_id: str,
    family: str,
    *,
    benchmark: str = "skilllearnbench",
) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain="skill_learning",
        prompt=task_id,
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
        artifact_path=f"rsebench-methods://skilllearnbench/tasks/{family}/{task_id}",
        verifier="skilllearn_hidden_test_v1",
        metadata={
            "task_family": family,
            "official_instance_path": f"rsebench-methods://skilllearnbench/tasks/{family}/{task_id}",
        },
    )


def _manifest(
    tmp_path: Path,
    *,
    benchmark: str = "skilllearnbench",
    sizes: tuple[int, int, int] = (2, 1, 2),
    feedback_mode: str = "self",
    runtime: dict | None = None,
) -> Path:
    family = "family"
    tasks = [
        _task(f"{family}-{index}", family, benchmark=benchmark)
        for index in range(1, sum(sizes) + 1)
    ]
    train_size, validation_size, _ = sizes
    split = CleanEvolutionSplitManifest(
        benchmark=benchmark,
        domain="skill_learning",
        seed=7,
        source_hash="a" * 64,
        train=tasks[:train_size],
        validation=tasks[train_size : train_size + validation_size],
        clean_test=tasks[train_size + validation_size :],
        metadata={
            "task_family": family,
            "feedback_mode": feedback_mode,
            "runtime": runtime or RUNTIME,
        },
    )
    path = tmp_path / "family.json"
    path.write_text(split.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_skilllearn_4096_config_only_changes_completion_budget() -> None:
    root = Path(__file__).resolve().parents[2]
    current = yaml.safe_load(
        (root / "configs/pilot/deepseek-v4-flash-generation.yaml").read_text()
    )
    clean = yaml.safe_load(
        (root / "configs/pilot/deepseek-v4-flash-4096.yaml").read_text()
    )
    assert clean == {**current, "max_tokens": 4096}


def test_clean_skilllearn_launcher_is_self_feedback_floor_tolerant(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}
    methods = tmp_path / "methods"
    for task_id in [f"family-{index}" for index in range(1, 6)]:
        instance = methods / f"skilllearnbench/tasks/family/{task_id}"
        (instance / "tests").mkdir(parents=True)
        (instance / "environment").mkdir()
    image_manifest = tmp_path / "image_manifest.json"
    image_manifest.write_text('{"all_ready": true}', encoding="utf-8")
    seed = tmp_path / "seed.md"
    seed.write_text("seed", encoding="utf-8")

    class FakeClient:
        @classmethod
        def from_yaml(cls, path):
            captured["provider_config"] = path
            return cls()

    class FakeBackend:
        def __init__(self, **kwargs):
            captured["backend"] = kwargs

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

    monkeypatch.setattr(run_clean_skilllearn, "DeepSeekClient", FakeClient)
    monkeypatch.setattr(run_clean_skilllearn, "DockerSkillLearnBackend", FakeBackend)
    monkeypatch.setattr(run_clean_skilllearn, "SkillLearnExecutor", FakeExecutor)
    monkeypatch.setattr(run_clean_skilllearn, "CleanEvolutionRunner", FakeRunner)
    monkeypatch.setattr(run_clean_skilllearn, "methods_root", lambda: methods)

    run_dir = run_clean_skilllearn.run_manifest(
        _manifest(tmp_path),
        seed_skill=seed,
        method_seed=20260813,
        output_root=tmp_path / "runs",
        image_manifest=image_manifest,
    )

    assert run_dir.name == "run-1"
    assert captured["backend"]["max_turns"] == 16
    assert captured["backend"]["require_prebuilt"] is True
    assert captured["executor"]["feedback_mode"] == "self"
    assert captured["executor"]["evidence_spec"] is None
    assert captured["run"]["policy"] == CleanQualificationPolicy()
    assert "seed_score_interval" not in captured["run"]
    assert captured["run"]["parameters"]["family"] == "family"


@pytest.mark.parametrize(
    ("benchmark", "sizes", "feedback_mode", "runtime", "message"),
    [
        ("other", (2, 1, 2), "self", RUNTIME, "only supports SkillLearnBench"),
        ("skilllearnbench", (1, 1, 3), "self", RUNTIME, "2/1/2-or-3"),
        ("skilllearnbench", (2, 1, 2), "teacher", RUNTIME, "self feedback"),
        (
            "skilllearnbench",
            (2, 1, 2),
            "self",
            {**RUNTIME, "max_completion_tokens": 2048},
            "runtime metadata differs",
        ),
    ],
)
def test_clean_skilllearn_launcher_rejects_contract_drift(
    tmp_path: Path,
    benchmark: str,
    sizes: tuple[int, int, int],
    feedback_mode: str,
    runtime: dict,
    message: str,
) -> None:
    seed = tmp_path / "seed.md"
    seed.write_text("seed", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        run_clean_skilllearn.run_manifest(
            _manifest(
                tmp_path,
                benchmark=benchmark,
                sizes=sizes,
                feedback_mode=feedback_mode,
                runtime=runtime,
            ),
            seed_skill=seed,
            method_seed=20260813,
            output_root=tmp_path / "runs",
            image_manifest=tmp_path / "images.json",
        )


def test_clean_skilllearn_dry_run_has_no_provider_or_executor_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed = tmp_path / "seed.md"
    seed.write_text("seed", encoding="utf-8")
    image_manifest = tmp_path / "images.json"
    image_manifest.write_text('{"all_ready": true}', encoding="utf-8")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("dry run must not construct provider or executor")

    monkeypatch.setattr(run_clean_skilllearn.DeepSeekClient, "from_yaml", forbidden)
    monkeypatch.setattr(run_clean_skilllearn, "SkillLearnExecutor", forbidden)

    run_dir = run_clean_skilllearn.run_manifest(
        _manifest(tmp_path),
        seed_skill=seed,
        method_seed=20260813,
        output_root=tmp_path / "preflight",
        image_manifest=image_manifest,
        dry_run=True,
    )

    assert calls == []
    payload = json.loads((run_dir / "dry_run.json").read_text(encoding="utf-8"))
    assert payload["provider_calls"] == 0
    assert payload["task_counts"] == {"train": 2, "validation": 1, "clean_test": 2}
    assert list(run_dir.rglob("*.jsonl")) == []
