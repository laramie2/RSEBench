"""Evaluate existing evolution artifacts on a larger untouched clean test set."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evolution.metrics import PairedEvolutionMetrics, compute_paired_metrics
from rsebench.evolution.runner import EvaluationResult, EvolutionExecutor
from rsebench.hashing import sha256_file


class TransitionCounts(StrictModel):
    """Paired clean-skill versus noisy-skill outcome transitions."""

    clean_correct_noisy_wrong: int = Field(ge=0)
    clean_wrong_noisy_correct: int = Field(ge=0)
    both_correct: int = Field(ge=0)
    both_wrong: int = Field(ge=0)
    net_harmful_flips: int


class ArtifactComparisonResult(StrictModel):
    """Auditable result of evaluating three fixed skill artifacts."""

    output_dir: str
    seed_skill_path: str
    clean_skill_path: str
    noisy_skill_path: str
    seed_skill_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    clean_skill_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    noisy_skill_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: PairedEvolutionMetrics
    transitions: TransitionCounts
    seed_evaluation: EvaluationResult
    clean_evaluation: EvaluationResult
    noisy_evaluation: EvaluationResult

    @property
    def seed_score(self) -> float:
        return self.metrics.seed_score

    @property
    def clean_evolved_score(self) -> float:
        return self.metrics.clean_evolved_score

    @property
    def noisy_evolved_score(self) -> float:
        return self.metrics.noisy_evolved_score


def count_transitions(
    *, clean: dict[str, float], noisy: dict[str, float]
) -> TransitionCounts:
    """Count paired binary-correctness transitions using exact task IDs."""

    if set(clean) != set(noisy):
        raise ValueError("paired evaluation task IDs differ")
    harmful = sum(clean[key] >= 1.0 and noisy[key] < 1.0 for key in clean)
    helpful = sum(clean[key] < 1.0 and noisy[key] >= 1.0 for key in clean)
    return TransitionCounts(
        clean_correct_noisy_wrong=harmful,
        clean_wrong_noisy_correct=helpful,
        both_correct=sum(clean[key] >= 1.0 and noisy[key] >= 1.0 for key in clean),
        both_wrong=sum(clean[key] < 1.0 and noisy[key] < 1.0 for key in clean),
        net_harmful_flips=harmful - helpful,
    )


def _write_json(path: Path, payload: object) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")  # type: ignore[union-attr]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve_source_run_skills(source_run: Path | str) -> dict[str, Path]:
    """Resolve the three skill files recorded by a paired evolution run."""

    run_dir = Path(source_run).resolve()
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        raise FileNotFoundError(f"source result not found: {result_path}")
    payload = json.loads(result_path.read_text(encoding="utf-8"))

    seed_candidates = sorted((run_dir / "seed").glob("*.md"))
    if len(seed_candidates) != 1:
        raise ValueError(
            f"expected exactly one source seed skill, found {len(seed_candidates)}"
        )

    def artifact_path(stage: str) -> Path:
        raw = str((payload.get(f"{stage}_artifact") or {}).get("skill_path") or "")
        candidate = Path(raw) if raw else run_dir / stage / "native_train/best_skill.md"
        if not candidate.is_absolute():
            candidate = run_dir / candidate
        return candidate.resolve()

    skills = {
        "seed": seed_candidates[0].resolve(),
        "clean": artifact_path("clean"),
        "noisy": artifact_path("noisy"),
    }
    for stage, skill_path in skills.items():
        if not skill_path.is_file():
            raise FileNotFoundError(f"{stage} skill not found: {skill_path}")
        expected_hash = str(payload.get(f"{stage}_skill_hash") or "")
        if sha256_file(skill_path) != expected_hash:
            raise ValueError(f"{stage} skill hash mismatch in source run")
    return skills


def evaluate_skill_artifacts(
    *,
    executor: EvolutionExecutor,
    seed_skill: Path | str,
    clean_skill: Path | str,
    noisy_skill: Path | str,
    clean_test: list[TaskManifest],
    output_dir: Path | str,
    bootstrap_samples: int = 2000,
    bootstrap_seed: int = 0,
) -> ArtifactComparisonResult:
    """Evaluate unique skill contents once and compare them on one clean test."""

    if not clean_test:
        raise ValueError("clean test must be non-empty")
    task_ids = [task.task_id for task in clean_test]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("clean test task IDs must be unique")

    skills = {
        "seed": Path(seed_skill).resolve(),
        "clean": Path(clean_skill).resolve(),
        "noisy": Path(noisy_skill).resolve(),
    }
    for stage, skill_path in skills.items():
        if not skill_path.is_file():
            raise FileNotFoundError(f"{stage} skill not found: {skill_path}")
    hashes = {stage: sha256_file(path) for stage, path in skills.items()}

    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    cache: dict[str, tuple[str, EvaluationResult]] = {}
    evaluations: dict[str, EvaluationResult] = {}
    for stage in ("seed", "clean", "noisy"):
        stage_dir = destination / stage
        stage_dir.mkdir()
        cached = cache.get(hashes[stage])
        if cached is not None:
            reused_stage, evaluation = cached
            _write_json(
                stage_dir / "reused.json",
                {
                    "reason": "identical_skill_hash",
                    "skill_hash": hashes[stage],
                    "reused_stage": reused_stage,
                },
            )
        else:
            evaluation = executor.evaluate(
                skill_path=skills[stage],
                clean_test=clean_test,
                output_dir=stage_dir,
                stage=stage,
            )
            cache[hashes[stage]] = (stage, evaluation)
        if set(evaluation.per_task_scores) != set(task_ids):
            raise ValueError(f"{stage} evaluation task IDs differ from clean test")
        evaluations[stage] = evaluation

    metrics = compute_paired_metrics(
        seed_scores=evaluations["seed"].per_task_scores,
        clean_scores=evaluations["clean"].per_task_scores,
        noisy_scores=evaluations["noisy"].per_task_scores,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )
    result = ArtifactComparisonResult(
        output_dir=str(destination),
        seed_skill_path=str(skills["seed"]),
        clean_skill_path=str(skills["clean"]),
        noisy_skill_path=str(skills["noisy"]),
        seed_skill_hash=hashes["seed"],
        clean_skill_hash=hashes["clean"],
        noisy_skill_hash=hashes["noisy"],
        metrics=metrics,
        transitions=count_transitions(
            clean=evaluations["clean"].per_task_scores,
            noisy=evaluations["noisy"].per_task_scores,
        ),
        seed_evaluation=evaluations["seed"],
        clean_evaluation=evaluations["clean"],
        noisy_evaluation=evaluations["noisy"],
    )
    _write_json(destination / "result.json", result)
    return result
