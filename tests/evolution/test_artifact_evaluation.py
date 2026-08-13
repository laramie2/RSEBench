from __future__ import annotations

from pathlib import Path

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution.artifact_evaluation import (
    count_transitions,
    evaluate_skill_artifacts,
    resolve_source_run_skills,
)
from rsebench.hashing import sha256_file
from rsebench.evolution.runner import EvaluationResult


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="demo",
        domain="math",
        prompt=f"Solve {task_id}",
        gold_answers=["1"],
        source_hash="0" * 64,
    )


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def evaluate(
        self,
        *,
        skill_path: Path,
        clean_test: list[TaskManifest],
        output_dir: Path,
        stage: str,
    ) -> EvaluationResult:
        self.calls.append((skill_path.name, stage))
        scores = {
            task.task_id: float(skill_path.read_text() == "good") for task in clean_test
        }
        return EvaluationResult(
            score=sum(scores.values()) / len(scores),
            per_task_scores=scores,
        )


def test_transition_counts_are_paired_by_task_id() -> None:
    counts = count_transitions(
        clean={"a": 1.0, "b": 0.0, "c": 1.0, "d": 0.0},
        noisy={"a": 0.0, "b": 1.0, "c": 1.0, "d": 0.0},
    )

    assert counts.model_dump() == {
        "clean_correct_noisy_wrong": 1,
        "clean_wrong_noisy_correct": 1,
        "both_correct": 1,
        "both_wrong": 1,
        "net_harmful_flips": 0,
    }


def test_transition_counts_require_identical_task_ids() -> None:
    with pytest.raises(ValueError, match="IDs differ"):
        count_transitions(clean={"a": 1.0}, noisy={"b": 0.0})


def test_identical_skill_hash_is_evaluated_once(tmp_path: Path) -> None:
    seed_skill = tmp_path / "seed.md"
    noisy_skill = tmp_path / "noisy.md"
    seed_skill.write_text("good", encoding="utf-8")
    noisy_skill.write_text("bad", encoding="utf-8")
    executor = RecordingExecutor()

    result = evaluate_skill_artifacts(
        executor=executor,
        seed_skill=seed_skill,
        clean_skill=seed_skill,
        noisy_skill=noisy_skill,
        clean_test=[_task("q1")],
        output_dir=tmp_path / "run",
        bootstrap_seed=7,
    )

    assert len(executor.calls) == 2
    assert result.seed_score == result.clean_evolved_score == 1.0
    assert result.noisy_evolved_score == 0.0
    assert result.transitions.clean_correct_noisy_wrong == 1
    assert result.transitions.net_harmful_flips == 1
    assert result.token_usage["attempted_calls"] == 0
    assert (tmp_path / "run/token_usage/summary.json").is_file()
    assert (tmp_path / "run/token_usage/report.md").is_file()
    assert (tmp_path / "run/clean/reused.json").is_file()


def test_evaluation_rejects_empty_clean_test(tmp_path: Path) -> None:
    skill = tmp_path / "seed.md"
    skill.write_text("good", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty"):
        evaluate_skill_artifacts(
            executor=RecordingExecutor(),
            seed_skill=skill,
            clean_skill=skill,
            noisy_skill=skill,
            clean_test=[],
            output_dir=tmp_path / "run",
        )


def test_source_run_skills_are_resolved_and_hash_checked(tmp_path: Path) -> None:
    run = tmp_path / "source"
    seed = run / "seed/initial.md"
    clean = run / "clean/native_train/best_skill.md"
    noisy = run / "noisy/native_train/best_skill.md"
    for path, content in ((seed, "seed"), (clean, "clean"), (noisy, "noisy")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (run / "result.json").write_text(
        __import__("json").dumps(
            {
                "seed_skill_hash": sha256_file(seed),
                "clean_skill_hash": sha256_file(clean),
                "noisy_skill_hash": sha256_file(noisy),
                "clean_artifact": {"skill_path": str(clean)},
                "noisy_artifact": {"skill_path": str(noisy)},
            }
        ),
        encoding="utf-8",
    )

    assert resolve_source_run_skills(run) == {
        "seed": seed.resolve(),
        "clean": clean.resolve(),
        "noisy": noisy.resolve(),
    }


def test_source_run_skill_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    run = tmp_path / "source"
    seed = run / "seed/initial.md"
    clean = run / "clean/native_train/best_skill.md"
    noisy = run / "noisy/native_train/best_skill.md"
    for path in (seed, clean, noisy):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
    (run / "result.json").write_text(
        __import__("json").dumps(
            {
                "seed_skill_hash": "f" * 64,
                "clean_skill_hash": sha256_file(clean),
                "noisy_skill_hash": sha256_file(noisy),
                "clean_artifact": {"skill_path": str(clean)},
                "noisy_artifact": {"skill_path": str(noisy)},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="seed skill hash mismatch"):
        resolve_source_run_skills(run)
