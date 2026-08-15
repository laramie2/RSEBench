"""Evaluate existing evolution artifacts on a larger untouched clean test set."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evolution.metrics import PairedEvolutionMetrics, compute_paired_metrics
from rsebench.evolution.runner import EvaluationResult, EvolutionExecutor
from rsebench.experiments.timing import TimingRecorder, TimingSpan, TimingSummary
from rsebench.hashing import sha256_file
from rsebench.usage import write_token_usage_artifacts


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
    token_usage: dict[str, Any]

    @property
    def seed_score(self) -> float:
        return self.metrics.seed_score

    @property
    def clean_evolved_score(self) -> float:
        return self.metrics.clean_evolved_score

    @property
    def noisy_evolved_score(self) -> float:
        return self.metrics.noisy_evolved_score


class FixedArtifactReplayObservation(StrictModel):
    """One isolated evaluation of one immutable skill artifact."""

    repeat: int = Field(ge=1)
    artifact_label: str = Field(min_length=1)
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: str = Field(min_length=1)
    started_at: str
    ended_at: str
    duration_seconds: float = Field(ge=0)
    evaluation: EvaluationResult


class FixedArtifactReplaySummary(StrictModel):
    """Across-repeat score and reference-delta summary for one artifact."""

    scores: list[float]
    mean_score: float
    score_sample_stddev: float = Field(ge=0)
    min_score: float
    max_score: float
    deltas_vs_reference: list[float]
    mean_delta_vs_reference: float
    delta_sample_stddev: float = Field(ge=0)


class FixedArtifactReplayResume(StrictModel):
    """One provider-active extension of an existing replay result."""

    from_repeat_count: int = Field(ge=2)
    to_repeat_count: int = Field(ge=3)
    started_at: str
    ended_at: str
    duration_seconds: float = Field(ge=0)


class RepeatedArtifactReplayResult(StrictModel):
    """Auditable repeated evaluation of arbitrary fixed skill artifacts."""

    schema_version: str = "rsebench.fixed-artifact-replay.v1"
    output_dir: str
    benchmark: str
    domain: str
    repeat_count: int = Field(ge=2)
    order_policy: str = "cyclic_rotation"
    artifact_order: list[str] = Field(default_factory=list)
    reference_label: str
    task_ids: list[str]
    task_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_paths: dict[str, str]
    artifact_hashes: dict[str, str]
    observations: list[FixedArtifactReplayObservation]
    summaries: dict[str, FixedArtifactReplaySummary]
    started_at: str
    ended_at: str
    duration_seconds: float = Field(ge=0)
    resume_history: list[FixedArtifactReplayResume] = Field(default_factory=list)
    timing: TimingSummary
    token_usage: dict[str, Any]


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


def _sample_stddev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _clean_test_task_ids(clean_test: list[TaskManifest]) -> list[str]:
    if not clean_test:
        raise ValueError("clean test must be non-empty")
    task_ids = [task.task_id for task in clean_test]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("clean test task IDs must be unique")
    return task_ids


def _snapshot_artifacts(
    *,
    destination: Path,
    artifacts: dict[str, Path],
    hashes: dict[str, str],
) -> dict[str, Path]:
    snapshots: dict[str, Path] = {}
    for label, source in artifacts.items():
        snapshot = destination / "artifacts" / label / source.name
        if not snapshot.is_file():
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, snapshot)
        if sha256_file(snapshot) != hashes[label]:
            raise ValueError(f"artifact snapshot hash differs: {label}")
        snapshots[label] = snapshot
    return snapshots


def evaluate_repeated_artifacts(
    *,
    executor: EvolutionExecutor,
    artifacts: dict[str, Path | str],
    reference_label: str,
    clean_test: list[TaskManifest],
    repeats: int,
    output_dir: Path | str,
    resume: bool = False,
) -> RepeatedArtifactReplayResult:
    """Evaluate immutable artifacts with cyclic rotation and paired deltas."""

    if repeats < 2:
        raise ValueError("repeated artifact evaluation requires at least 2 repeats")
    task_ids = _clean_test_task_ids(clean_test)
    if reference_label not in artifacts:
        raise ValueError(f"reference artifact is missing: {reference_label}")
    if not artifacts:
        raise ValueError("at least one artifact is required")
    label_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    for label in artifacts:
        if not label_pattern.fullmatch(label):
            raise ValueError(f"invalid artifact label: {label}")

    resolved = {label: Path(path).resolve() for label, path in artifacts.items()}
    for label, path in resolved.items():
        if not path.is_file():
            raise FileNotFoundError(f"artifact {label} not found: {path}")
    hashes = {label: sha256_file(path) for label, path in resolved.items()}
    task_payload = [task.model_dump(mode="json") for task in clean_test]
    task_manifest_hash = hashlib.sha256(
        json.dumps(
            task_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    destination = Path(output_dir).resolve()
    labels = list(resolved)
    existing: RepeatedArtifactReplayResult | None = None
    if resume:
        result_path = destination / "result.json"
        if not result_path.is_file():
            raise FileNotFoundError(f"replay result not found for resume: {result_path}")
        existing = RepeatedArtifactReplayResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        existing_order = existing.artifact_order or [
            observation.artifact_label
            for observation in existing.observations
            if observation.repeat == 1
        ]
        expected_pairs = {
            (repeat, label)
            for repeat in range(1, existing.repeat_count + 1)
            for label in existing_order
        }
        observed_pairs = {
            (observation.repeat, observation.artifact_label)
            for observation in existing.observations
        }
        if len(observed_pairs) != len(existing.observations):
            raise ValueError("existing replay contains duplicate observations")
        if observed_pairs != expected_pairs:
            raise ValueError("existing replay observations are incomplete")
        if existing.order_policy != "cyclic_rotation":
            raise ValueError("existing replay order policy differs")
        if existing_order != labels:
            raise ValueError("existing replay artifact order differs")
        if existing.reference_label != reference_label:
            raise ValueError("existing replay reference label differs")
        if existing.artifact_hashes != hashes:
            raise ValueError("existing replay artifact hashes differ")
        if existing.task_manifest_hash != task_manifest_hash:
            raise ValueError("existing replay task manifest hash differs")
        if existing.task_ids != task_ids:
            raise ValueError("existing replay task IDs differ")
        if existing.benchmark != clean_test[0].benchmark:
            raise ValueError("existing replay benchmark differs")
        if existing.domain != clean_test[0].domain:
            raise ValueError("existing replay domain differs")
        if repeats <= existing.repeat_count:
            raise ValueError("resume repeat target must exceed existing repeat count")
    else:
        destination.mkdir(parents=True, exist_ok=False)
    snapshots = _snapshot_artifacts(
        destination=destination,
        artifacts=resolved,
        hashes=hashes,
    )
    configure_token_run = getattr(executor, "configure_token_run", None)
    if callable(configure_token_run):
        configure_token_run(destination)

    recorder = TimingRecorder(destination)
    configure_timing = getattr(executor, "configure_timing", None)
    if callable(configure_timing):
        configure_timing(recorder)
    observations = list(existing.observations) if existing else []
    scores: dict[str, list[float]] = {label: [] for label in resolved}
    for observation in observations:
        scores[observation.artifact_label].append(observation.evaluation.score)
    first_repeat = existing.repeat_count + 1 if existing else 1
    try:
        with recorder.span(level="run", name="fixed_artifact_replay"):
            for repeat in range(first_repeat, repeats + 1):
                offset = (repeat - 1) % len(labels)
                evaluation_order = labels[offset:] + labels[:offset]
                for label in evaluation_order:
                    artifact_path = snapshots[label]
                    stage = f"replay_{label}_r{repeat}"
                    evaluation_dir = destination / f"repeat-{repeat:03d}" / label
                    evaluation_started_at = datetime.now(timezone.utc)
                    evaluation_started_clock = time.monotonic()
                    if sha256_file(artifact_path) != hashes[label]:
                        raise ValueError(f"artifact snapshot hash differs: {label}")
                    with recorder.span(
                        level="stage",
                        name=stage,
                        metadata={
                            "artifact_label": label,
                            "artifact_hash": hashes[label],
                            "repeat": repeat,
                        },
                    ):
                        evaluation = executor.evaluate(
                            skill_path=artifact_path,
                            clean_test=clean_test,
                            output_dir=evaluation_dir,
                            stage=stage,
                        )
                    if sha256_file(artifact_path) != hashes[label]:
                        raise ValueError(f"artifact snapshot hash differs: {label}")
                    evaluation_ended_at = datetime.now(timezone.utc)
                    observation = FixedArtifactReplayObservation(
                        repeat=repeat,
                        artifact_label=label,
                        artifact_hash=hashes[label],
                        stage=stage,
                        started_at=evaluation_started_at.isoformat(),
                        ended_at=evaluation_ended_at.isoformat(),
                        duration_seconds=time.monotonic() - evaluation_started_clock,
                        evaluation=evaluation,
                    )
                    observations.append(observation)
                    scores[label].append(evaluation.score)
                    _write_json(evaluation_dir / "result.json", observation)
    finally:
        active_timing = recorder.finalize()
        token_usage = write_token_usage_artifacts(destination / "token_usage")

    reference_scores = scores[reference_label]
    summaries: dict[str, FixedArtifactReplaySummary] = {}
    for label, label_scores in scores.items():
        deltas = [
            score - reference
            for score, reference in zip(label_scores, reference_scores, strict=True)
        ]
        summaries[label] = FixedArtifactReplaySummary(
            scores=label_scores,
            mean_score=statistics.fmean(label_scores),
            score_sample_stddev=_sample_stddev(label_scores),
            min_score=min(label_scores),
            max_score=max(label_scores),
            deltas_vs_reference=deltas,
            mean_delta_vs_reference=statistics.fmean(deltas),
            delta_sample_stddev=_sample_stddev(deltas),
        )

    timing = active_timing
    if existing:
        timing = TimingSummary(
            run=TimingSpan(
                level="run",
                name="fixed_artifact_replay",
                started_at=existing.timing.run.started_at,
                ended_at=active_timing.run.ended_at,
                duration_seconds=(
                    existing.timing.run.duration_seconds
                    + active_timing.run.duration_seconds
                ),
                status="completed",
            ),
            stages=[*existing.timing.stages, *active_timing.stages],
            tasks=[*existing.timing.tasks, *active_timing.tasks],
        )
        _write_json(destination / "timing/summary.json", timing)
    resume_history = list(existing.resume_history) if existing else []
    if existing:
        resume_history.append(
            FixedArtifactReplayResume(
                from_repeat_count=existing.repeat_count,
                to_repeat_count=repeats,
                started_at=active_timing.run.started_at.isoformat(),
                ended_at=active_timing.run.ended_at.isoformat(),
                duration_seconds=active_timing.run.duration_seconds,
            )
        )
    result = RepeatedArtifactReplayResult(
        output_dir=str(destination),
        benchmark=clean_test[0].benchmark,
        domain=clean_test[0].domain,
        repeat_count=repeats,
        order_policy="cyclic_rotation",
        artifact_order=labels,
        reference_label=reference_label,
        task_ids=task_ids,
        task_manifest_hash=task_manifest_hash,
        artifact_paths={label: str(path) for label, path in resolved.items()},
        artifact_hashes=hashes,
        observations=observations,
        summaries=summaries,
        started_at=(
            existing.started_at
            if existing
            else active_timing.run.started_at.isoformat()
        ),
        ended_at=active_timing.run.ended_at.isoformat(),
        duration_seconds=timing.run.duration_seconds,
        resume_history=resume_history,
        timing=timing,
        token_usage=token_usage,
    )
    _write_json(destination / "result.json", result)
    return result


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

    task_ids = _clean_test_task_ids(clean_test)

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
    configure_token_run = getattr(executor, "configure_token_run", None)
    if callable(configure_token_run):
        configure_token_run(destination)
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
    token_usage = write_token_usage_artifacts(destination / "token_usage")
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
        token_usage=token_usage,
    )
    _write_json(destination / "result.json", result)
    return result
