"""Append-only orchestration for clean baseline qualification."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rsebench.contracts import StrictModel
from rsebench.evolution.clean_bridge import build_clean_runtime_split
from rsebench.evolution.clean_contracts import (
    CleanEvolutionSplitManifest,
    CleanQualificationDecision,
    CleanQualificationPolicy,
)
from rsebench.evolution.pairs import build_clean_arm_manifest
from rsebench.evolution.runner import (
    EvaluationResult,
    EvolutionArtifact,
    EvolutionExecutor,
)
from rsebench.hashing import sha256_file
from rsebench.usage import write_token_usage_artifacts


class CleanQualificationRunError(RuntimeError):
    """Raised after an operational clean-qualification failure is persisted."""

    def __init__(self, message: str, *, run_dir: Path):
        super().__init__(message)
        self.run_dir = run_dir


class CleanEvolutionResult(StrictModel):
    run_dir: str
    method: str
    method_seed: int
    seed_skill_hash: str
    clean_skill_hash: str
    seed_evaluation: EvaluationResult
    clean_evaluation: EvaluationResult
    clean_artifact: EvolutionArtifact
    qualification: CleanQualificationDecision
    token_usage: dict[str, Any]


def _has_execution_failure(evaluation: EvaluationResult) -> bool:
    return bool(evaluation.diagnostics.get("execution_failures"))


def _threshold_failed(
    evaluations: tuple[EvaluationResult, EvaluationResult],
    *,
    key: str,
    threshold: float | None,
    minimum: bool,
) -> bool:
    if threshold is None:
        return False
    for evaluation in evaluations:
        value = evaluation.diagnostics.get(key)
        if not isinstance(value, (int, float)):
            return True
        if minimum and value < threshold:
            return True
        if not minimum and value > threshold:
            return True
    return False


def _qualify(
    *,
    split: CleanEvolutionSplitManifest,
    seed_hash: str,
    artifact: EvolutionArtifact,
    seed_evaluation: EvaluationResult,
    clean_evaluation: EvaluationResult,
    policy: CleanQualificationPolicy,
) -> CleanQualificationDecision:
    reasons: list[str] = []
    expected_train = {task.task_id for task in split.train}
    expected_validation = {task.task_id for task in split.validation}
    expected_test = {task.task_id for task in split.clean_test}
    audit = artifact.execution_audit

    if audit is None:
        reasons.append("missing_execution_audit")
        train_covered = False
        validation_covered = False
        accepted_update_count = 0
    else:
        train_covered = set(audit.train_task_ids) == expected_train
        validation_covered = set(audit.validation_task_ids) == expected_validation
        accepted_update_count = audit.accepted_update_count
        if not train_covered:
            reasons.append("train_execution_coverage")
        if not validation_covered:
            reasons.append("validation_execution_coverage")

    test_covered = (
        set(seed_evaluation.per_task_scores) == expected_test
        and set(clean_evaluation.per_task_scores) == expected_test
    )
    if not test_covered:
        reasons.append("clean_test_execution_coverage")

    artifact_updated = artifact.skill_hash != seed_hash
    if not artifact_updated:
        reasons.append("artifact_unchanged")
    if accepted_update_count == 0:
        reasons.append("no_accepted_update")

    clean_gain = clean_evaluation.score - seed_evaluation.score
    nondegrading = clean_gain >= 0.0
    if not nondegrading:
        reasons.append("clean_score_decreased")

    evaluations = (seed_evaluation, clean_evaluation)
    if _threshold_failed(
        evaluations,
        key="parseable_answer_rate",
        threshold=policy.min_parseable_answer_rate,
        minimum=True,
    ):
        reasons.append("parseable_answer_rate")
    if _threshold_failed(
        evaluations,
        key="systemic_failure_rate",
        threshold=policy.max_systemic_failure_rate,
        minimum=False,
    ):
        reasons.append("systemic_failure_rate")
    if any(_has_execution_failure(evaluation) for evaluation in evaluations):
        reasons.append("execution_failure")

    execution_coverage_passed = (
        audit is not None and train_covered and validation_covered and test_covered
    )
    runtime_reasons = {
        "parseable_answer_rate",
        "systemic_failure_rate",
        "execution_failure",
    }
    runtime_gates_passed = not any(reason in runtime_reasons for reason in reasons)
    passed = (
        execution_coverage_passed
        and artifact_updated
        and accepted_update_count > 0
        and nondegrading
        and runtime_gates_passed
    )
    return CleanQualificationDecision(
        execution_coverage_passed=execution_coverage_passed,
        artifact_updated=artifact_updated,
        accepted_update_count=accepted_update_count,
        nondegrading=nondegrading,
        runtime_gates_passed=runtime_gates_passed,
        seed_score=seed_evaluation.score,
        evolved_score=clean_evaluation.score,
        clean_gain=clean_gain,
        strictly_positive_gain=clean_gain > 0.0,
        passed=passed,
        failure_reasons=reasons,
    )


class CleanEvolutionRunner:
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
        split: CleanEvolutionSplitManifest,
        seed_skill_path: Path | str,
        method_seed: int,
        parameters: dict[str, Any],
        output_root: Path | str,
        policy: CleanQualificationPolicy | None = None,
    ) -> CleanEvolutionResult:
        source_seed = Path(seed_skill_path).resolve()
        if not source_seed.is_file():
            raise FileNotFoundError(f"seed skill not found: {source_seed}")
        seed_hash = sha256_file(source_seed)
        run_dir = self._new_run_dir(Path(output_root), method)
        try:
            configure_token_run = getattr(self.executor, "configure_token_run", None)
            if callable(configure_token_run):
                configure_token_run(run_dir)
            self._write_json(run_dir / "split_manifest.json", split)

            seed_dir = run_dir / "seed"
            clean_dir = run_dir / "clean"
            seed_dir.mkdir()
            clean_dir.mkdir()
            canonical_seed = seed_dir / source_seed.name
            clean_seed = clean_dir / f"seed-{source_seed.name}"
            shutil.copy2(source_seed, canonical_seed)
            shutil.copy2(canonical_seed, clean_seed)

            seed_eval_dir = seed_dir / "evaluation"
            seed_eval_dir.mkdir()
            seed_evaluation = self.executor.evaluate(
                skill_path=canonical_seed,
                clean_test=split.clean_test,
                output_dir=seed_eval_dir,
                stage="seed",
            )
            self._write_json(seed_eval_dir / "result.json", seed_evaluation)

            runtime_split = build_clean_runtime_split(split)
            clean_arm = build_clean_arm_manifest(
                runtime_split,
                method=method,
                method_seed=method_seed,
                seed_skill_hash=seed_hash,
                parameters=parameters,
            )
            self._write_json(clean_dir / "arm_manifest.json", clean_arm)
            artifact = self.executor.evolve(
                arm=clean_arm,
                split=runtime_split,
                seed_skill_path=clean_seed,
                output_dir=clean_dir,
            )
            if sha256_file(clean_seed) != seed_hash:
                raise RuntimeError("seed skill mutated in clean arm")
            artifact_path = Path(artifact.skill_path)
            if not artifact_path.is_file():
                raise RuntimeError(f"evolved skill is missing: {artifact_path}")
            if sha256_file(artifact_path) != artifact.skill_hash:
                raise RuntimeError("evolved skill hash mismatch in clean arm")
            self._write_json(clean_dir / "evolution_artifact.json", artifact)

            evaluation_dir = clean_dir / "clean_test_evaluation"
            evaluation_dir.mkdir(exist_ok=False)
            if artifact.skill_hash == seed_hash:
                clean_evaluation = seed_evaluation
                self._write_json(
                    evaluation_dir / "reused.json",
                    {
                        "reason": "identical_skill_hash",
                        "skill_hash": artifact.skill_hash,
                        "reused_stage": "seed",
                    },
                )
            else:
                clean_evaluation = self.executor.evaluate(
                    skill_path=artifact_path,
                    clean_test=split.clean_test,
                    output_dir=evaluation_dir,
                    stage="clean",
                )
            self._write_json(evaluation_dir / "result.json", clean_evaluation)

            qualification = _qualify(
                split=split,
                seed_hash=seed_hash,
                artifact=artifact,
                seed_evaluation=seed_evaluation,
                clean_evaluation=clean_evaluation,
                policy=policy or CleanQualificationPolicy(),
            )
            self._write_json(run_dir / "qualification.json", qualification)
            token_usage = write_token_usage_artifacts(run_dir / "token_usage")
            result = CleanEvolutionResult(
                run_dir=str(run_dir),
                method=method,
                method_seed=method_seed,
                seed_skill_hash=seed_hash,
                clean_skill_hash=artifact.skill_hash,
                seed_evaluation=seed_evaluation,
                clean_evaluation=clean_evaluation,
                clean_artifact=artifact,
                qualification=qualification,
                token_usage=token_usage,
            )
            self._write_json(run_dir / "result.json", result)
            from rsebench.evolution.clean_report import render_clean_report

            (run_dir / "report.md").write_text(
                render_clean_report(result), encoding="utf-8"
            )
            return result
        except Exception as exc:
            self._write_json(
                run_dir / "failure.json",
                {"exception_type": type(exc).__name__, "message": str(exc)},
            )
            write_token_usage_artifacts(run_dir / "token_usage")
            raise CleanQualificationRunError(
                f"clean qualification failed: {exc}", run_dir=run_dir
            ) from exc
