"""Append-only orchestration for paired clean/noisy self-evolution."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evolution.contracts import (
    EvolutionArmManifest,
    EvolutionSplitManifest,
)
from rsebench.evolution.metrics import PairedEvolutionMetrics, compute_paired_metrics
from rsebench.evolution.pairs import build_arm_manifests
from rsebench.hashing import sha256_file
from rsebench.usage import write_token_usage_artifacts


class EvolutionArtifact(StrictModel):
    skill_path: str = Field(min_length=1)
    skill_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(StrictModel):
    score: float
    per_task_scores: dict[str, float]
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class EvolutionExecutor(Protocol):
    def evolve(
        self,
        *,
        arm: EvolutionArmManifest,
        split: EvolutionSplitManifest,
        seed_skill_path: Path,
        output_dir: Path,
    ) -> EvolutionArtifact: ...

    def evaluate(
        self,
        *,
        skill_path: Path,
        clean_test: list[TaskManifest],
        output_dir: Path,
        stage: str,
    ) -> EvaluationResult: ...


class PairedEvolutionResult(StrictModel):
    run_dir: str
    method: str
    seed_skill_hash: str
    clean_skill_hash: str
    noisy_skill_hash: str
    metrics: PairedEvolutionMetrics
    seed_evaluation: EvaluationResult
    clean_evaluation: EvaluationResult
    noisy_evaluation: EvaluationResult
    clean_artifact: EvolutionArtifact
    noisy_artifact: EvolutionArtifact
    token_usage: dict[str, Any]


class PairedEvolutionRunner:
    def __init__(self, executor: EvolutionExecutor):
        self.executor = executor

    @staticmethod
    def _new_run_dir(output_root: Path, method: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = output_root / f"{stamp}-{method}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def run(
        self,
        *,
        method: str,
        split: EvolutionSplitManifest,
        seed_skill_path: Path | str,
        method_seed: int,
        parameters: dict[str, Any],
        output_root: Path | str,
    ) -> PairedEvolutionResult:
        source_seed = Path(seed_skill_path).resolve()
        if not source_seed.is_file():
            raise FileNotFoundError(f"seed skill not found: {source_seed}")
        seed_hash = sha256_file(source_seed)
        run_dir = self._new_run_dir(Path(output_root), method)
        configure_token_run = getattr(self.executor, "configure_token_run", None)
        if callable(configure_token_run):
            configure_token_run(run_dir)
        self._write_json(run_dir / "split_manifest.json", split)

        seed_dir = run_dir / "seed"
        seed_dir.mkdir()
        canonical_seed = seed_dir / source_seed.name
        shutil.copy2(source_seed, canonical_seed)
        arm_seed_paths: dict[str, Path] = {}
        for arm_name in ("clean", "noisy"):
            arm_dir = run_dir / arm_name
            arm_dir.mkdir()
            arm_seed = arm_dir / f"seed-{source_seed.name}"
            shutil.copy2(canonical_seed, arm_seed)
            arm_seed_paths[arm_name] = arm_seed

        clean_arm, noisy_arm = build_arm_manifests(
            split,
            method=method,
            method_seed=method_seed,
            seed_skill_hash=seed_hash,
            parameters=parameters,
        )
        self._write_json(run_dir / "clean" / "arm_manifest.json", clean_arm)
        self._write_json(run_dir / "noisy" / "arm_manifest.json", noisy_arm)

        seed_eval_dir = seed_dir / "evaluation"
        seed_eval_dir.mkdir()
        seed_evaluation = self.executor.evaluate(
            skill_path=canonical_seed,
            clean_test=split.clean_test,
            output_dir=seed_eval_dir,
            stage="seed",
        )
        evaluation_cache: dict[str, tuple[str, EvaluationResult]] = {
            seed_hash: ("seed", seed_evaluation)
        }

        artifacts: dict[str, EvolutionArtifact] = {}
        evaluations: dict[str, EvaluationResult] = {}
        for arm in (clean_arm, noisy_arm):
            arm_dir = run_dir / arm.arm
            artifact = self.executor.evolve(
                arm=arm,
                split=split,
                seed_skill_path=arm_seed_paths[arm.arm],
                output_dir=arm_dir,
            )
            if sha256_file(arm_seed_paths[arm.arm]) != seed_hash:
                raise RuntimeError(f"seed skill mutated in {arm.arm} arm")
            artifact_path = Path(artifact.skill_path)
            if not artifact_path.is_file():
                raise RuntimeError(f"evolved skill is missing: {artifact_path}")
            if sha256_file(artifact_path) != artifact.skill_hash:
                raise RuntimeError(f"evolved skill hash mismatch in {arm.arm} arm")
            evaluation_dir = arm_dir / "clean_test_evaluation"
            evaluation_dir.mkdir(exist_ok=False)
            cached = evaluation_cache.get(artifact.skill_hash)
            if cached is not None:
                reused_stage, evaluation = cached
                self._write_json(
                    evaluation_dir / "reused.json",
                    {
                        "reason": "identical_skill_hash",
                        "skill_hash": artifact.skill_hash,
                        "reused_stage": reused_stage,
                    },
                )
            else:
                evaluation = self.executor.evaluate(
                    skill_path=artifact_path,
                    clean_test=split.clean_test,
                    output_dir=evaluation_dir,
                    stage=arm.arm,
                )
                evaluation_cache[artifact.skill_hash] = (arm.arm, evaluation)
            artifacts[arm.arm] = artifact
            evaluations[arm.arm] = evaluation

        metrics = compute_paired_metrics(
            seed_scores=seed_evaluation.per_task_scores,
            clean_scores=evaluations["clean"].per_task_scores,
            noisy_scores=evaluations["noisy"].per_task_scores,
            bootstrap_seed=method_seed,
        )
        token_usage = write_token_usage_artifacts(run_dir / "token_usage")
        result = PairedEvolutionResult(
            run_dir=str(run_dir),
            method=method,
            seed_skill_hash=seed_hash,
            clean_skill_hash=artifacts["clean"].skill_hash,
            noisy_skill_hash=artifacts["noisy"].skill_hash,
            metrics=metrics,
            seed_evaluation=seed_evaluation,
            clean_evaluation=evaluations["clean"],
            noisy_evaluation=evaluations["noisy"],
            clean_artifact=artifacts["clean"],
            noisy_artifact=artifacts["noisy"],
            token_usage=token_usage,
        )
        self._write_json(run_dir / "result.json", result)
        from rsebench.evolution.report import render_paired_report

        (run_dir / "report.md").write_text(
            render_paired_report(result), encoding="utf-8"
        )
        return result
