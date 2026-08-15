from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.evolution.runner import EvaluationResult
from rsebench.selection.contracts import StableSplitCandidate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAMILY = "organize-messy-files"


def _load_script():
    path = PROJECT_ROOT / "scripts/replay_fixed_skilllearn_artifacts.py"
    assert path.is_file(), "SkillLearn fixed-artifact replay CLI is missing"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="skilllearnbench",
        domain="skill_learning",
        prompt=task_id,
        gold_answers=[],
        verifier="skilllearn_hidden_test_v1",
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
        artifact_path=f"rsebench-methods://skilllearnbench/tasks/{task_id}",
        metadata={"task_family": FAMILY},
    )


def _manifest(tmp_path: Path) -> Path:
    roles = {
        "train": [_task(f"{FAMILY}-1"), _task(f"{FAMILY}-2")],
        "validation": [_task(f"{FAMILY}-3")],
        "qualification_test": [],
        "screening_test": [_task(f"{FAMILY}-4"), _task(f"{FAMILY}-5")],
    }
    candidate = StableSplitCandidate(
        benchmark="skilllearnbench",
        domain="skill_learning",
        candidate_index=1,
        source_hash=canonical_hash(
            {
                key: [task.model_dump(mode="json") for task in value]
                for key, value in roles.items()
            }
        ),
        selection_hash=canonical_hash(
            {key: [task.task_id for task in value] for key, value in roles.items()}
        ),
        metadata={
            "qualification_version": "noise-screen-v1",
            "source_seed": 20260813,
            "families": [FAMILY],
            "runtime": {
                "evolution_rounds": 2,
                "max_completion_tokens": 4096,
                "max_tool_turns": 16,
                "require_prebuilt_images": True,
            },
            "feedback_mode": "self",
            "static_audit": {
                "family_allocations": {
                    FAMILY: {
                        "train": [f"{FAMILY}-1", f"{FAMILY}-2"],
                        "validation": [f"{FAMILY}-3"],
                        "screening_test": [f"{FAMILY}-4", f"{FAMILY}-5"],
                    }
                }
            },
        },
        **roles,
    )
    path = tmp_path / "candidate.json"
    path.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")
    return path


class _FakeExecutor:
    def __init__(self, **_kwargs) -> None:
        self.timing = None

    def configure_token_run(self, _output_dir: Path) -> None:
        pass

    def configure_timing(self, recorder) -> None:
        self.timing = recorder

    def evaluate(self, *, skill_path, clean_test, output_dir, stage):
        assert skill_path.suffix == ".md"
        assert self.timing is not None
        output_dir.mkdir(parents=True)
        scores = {}
        for task in clean_test:
            with self.timing.span(level="task", name=stage, task_id=task.task_id):
                scores[task.task_id] = 1.0
        return EvaluationResult(score=1.0, per_task_scores=scores)


def test_skilllearn_replay_uses_family_screening_tail_and_records_full_accounting(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "SkillLearnExecutor", _FakeExecutor)
    monkeypatch.setattr(module, "resolve_selection_candidate_paths", lambda row: row)
    monkeypatch.setattr(
        module, "build_skilllearn_executor", lambda **_kwargs: _FakeExecutor()
    )
    artifacts = []
    for label in ("seed", "clean"):
        path = tmp_path / f"{label}.md"
        path.write_text(label + "\n", encoding="utf-8")
        artifacts.append(f"{label}={path}")
    output = tmp_path / "replay"
    image_manifest = tmp_path / "images.json"
    image_manifest.write_text(json.dumps({"all_ready": True}), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--manifest",
            str(_manifest(tmp_path)),
            "--family",
            FAMILY,
            "--image-manifest",
            str(image_manifest),
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
    assert payload["task_ids"] == [f"{FAMILY}-4", f"{FAMILY}-5"]
    assert payload["duration_seconds"] >= 0
    assert len(payload["timing"]["stages"]) == 6
    assert len(payload["timing"]["tasks"]) == 12
    usage = payload["token_usage"]
    assert usage["billed_tokens"]["prompt_tokens"] == 0
    assert usage["billed_tokens"]["completion_tokens"] == 0
    assert usage["billed_tokens"]["total_tokens"] == 0
    assert usage["observed_coverage"] == 1.0


def test_skilllearn_dry_run_does_not_construct_provider_client(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    artifact = tmp_path / "seed.md"
    artifact.write_text("seed\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        module,
        "build_skilllearn_executor",
        lambda **kwargs: calls.append(kwargs),
    )
    output = tmp_path / "replay"
    image_manifest = tmp_path / "images.json"
    image_manifest.write_text(json.dumps({"all_ready": True}), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--manifest",
            str(_manifest(tmp_path)),
            "--family",
            FAMILY,
            "--image-manifest",
            str(image_manifest),
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
    assert calls == []
