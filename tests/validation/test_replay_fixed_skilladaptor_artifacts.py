from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.evolution.runner import EvaluationResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    path = PROJECT_ROOT / "scripts/replay_fixed_skilladaptor_artifacts.py"
    assert path.is_file(), "SkillAdaptor fixed-artifact replay CLI is missing"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="webshop",
        domain="interactive",
        prompt=task_id,
        gold_answers=["ok"],
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
        metadata={"goal_idx": int(task_id.split("_")[-1])},
    )


def _manifest(tmp_path: Path) -> Path:
    split = CleanEvolutionSplitManifest(
        benchmark="webshop",
        domain="interactive",
        seed=20260813,
        source_hash="a" * 64,
        train=[_task(f"goal_{index}") for index in range(1, 6)],
        validation=[_task(f"goal_{index}") for index in range(6, 11)],
        clean_test=[_task(f"goal_{index}") for index in range(11, 31)],
        metadata={
            "qualification_version": "noise-screen-v1",
            "runtime": {
                "max_iterations": 3,
                "max_episode_steps": 15,
                "min_sample_size": 5,
            },
        },
    )
    path = tmp_path / "manifest.json"
    path.write_text(split.model_dump_json(indent=2), encoding="utf-8")
    return path


class _FakeExecutor:
    init_kwargs = None

    def __init__(self, **kwargs) -> None:
        type(self).init_kwargs = kwargs
        self.timing = None

    def configure_token_run(self, _output_dir: Path) -> None:
        pass

    def configure_timing(self, recorder) -> None:
        self.timing = recorder

    def evaluate(self, *, skill_path, clean_test, output_dir, stage):
        assert skill_path.is_file()
        assert self.timing is not None
        output_dir.mkdir(parents=True)
        scores = {}
        for task in clean_test:
            with self.timing.span(level="task", name=stage, task_id=task.task_id):
                scores[task.task_id] = 1.0
        return EvaluationResult(score=1.0, per_task_scores=scores)


def test_skilladaptor_replay_delegates_rotation_timing_and_tokens(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "SkillAdaptorExecutor", _FakeExecutor)
    monkeypatch.setattr(module, "methods_root", lambda: tmp_path / "methods")
    monkeypatch.setattr(module, "combined_method_env", lambda _method: {})
    artifacts = []
    for label in ("seed", "clean"):
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps({"label": label}), encoding="utf-8")
        artifacts.append(f"{label}={path}")
    output = tmp_path / "replay"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--manifest",
            str(_manifest(tmp_path)),
            "--artifact",
            artifacts[0],
            "--artifact",
            artifacts[1],
            "--reference",
            "seed",
            "--repeats",
            "3",
            "--output-dir",
            str(output),
            "--confirm-provider-cost",
        ],
    )

    module.main()

    payload = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert _FakeExecutor.init_kwargs["budget"].max_episode_steps == 15
    assert payload["duration_seconds"] >= 0
    assert payload["timing"]["run"]["level"] == "run"
    assert len(payload["timing"]["stages"]) == 6
    assert len(payload["timing"]["tasks"]) == 120
    usage = payload["token_usage"]
    assert usage["billed_tokens"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert usage["observed_coverage"] == 1.0


def test_skilladaptor_replay_dry_run_has_zero_provider_calls(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    artifact = tmp_path / "seed.json"
    artifact.write_text("{}", encoding="utf-8")
    output = tmp_path / "replay"
    monkeypatch.setattr(module, "methods_root", lambda: tmp_path / "methods")
    monkeypatch.setattr(module, "combined_method_env", lambda _method: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--manifest",
            str(_manifest(tmp_path)),
            "--artifact",
            f"seed={artifact}",
            "--reference",
            "seed",
            "--output-dir",
            str(output),
            "--dry-run",
        ],
    )

    module.main()

    plan = json.loads(output.with_name("replay.plan.json").read_text(encoding="utf-8"))
    assert plan["provider_calls"] == 0
    assert not output.exists()
