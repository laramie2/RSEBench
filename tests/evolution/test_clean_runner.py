import hashlib
import json
from pathlib import Path

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_contracts import (
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
    EvolutionExecutionAudit,
)
from rsebench.evolution.clean_runner import (
    CleanEvolutionRunner,
    CleanQualificationRunError,
)
from rsebench.evolution.runner import EvaluationResult, EvolutionArtifact
from rsebench.experiments.bootstrap import BaselineFingerprint
from rsebench.experiments.contracts import (
    ExperimentIdentityInput,
    build_attempt_identity,
    build_experiment_identity,
)
from rsebench.usage import record_token_event


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="document",
        prompt=f"clean {task_id}",
        gold_answers=["x"],
        source_hash=_hash(task_id),
    )


def _split() -> CleanEvolutionSplitManifest:
    return CleanEvolutionSplitManifest(
        benchmark="fixture",
        domain="document",
        seed=7,
        source_hash=_hash("split"),
        train=[_task("train")],
        validation=[_task("validation")],
        clean_test=[_task("test")],
        metadata={"config_version": "clean-qualification-v1"},
    )


class FixtureExecutor:
    def __init__(
        self,
        *,
        audit: EvolutionExecutionAudit | None = None,
        seed_score: float = 0.25,
        clean_score: float = 0.75,
        artifact_updated: bool = True,
        evaluation_diagnostics: dict[str, dict] | None = None,
        evolve_error: Exception | None = None,
    ) -> None:
        self.audit = audit or EvolutionExecutionAudit(
            train_task_ids=["train"],
            validation_task_ids=["validation"],
            accepted_update_count=1,
        )
        self.seed_score = seed_score
        self.clean_score = clean_score
        self.artifact_updated = artifact_updated
        self.evaluation_diagnostics = evaluation_diagnostics or {}
        self.evolve_error = evolve_error
        self.evaluate_calls: list[str] = []
        self.evolve_calls = []
        self.timing = None

    def configure_token_run(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def configure_timing(self, recorder) -> None:
        self.timing = recorder

    def evolve(self, *, arm, split, seed_skill_path, output_dir):
        self.evolve_calls.append(arm)
        if self.evolve_error is not None:
            raise self.evolve_error
        artifact = output_dir / "evolved.md"
        if self.artifact_updated:
            artifact.write_text("evolved skill", encoding="utf-8")
        else:
            artifact.write_bytes(seed_skill_path.read_bytes())
        return EvolutionArtifact(
            skill_path=str(artifact),
            skill_hash=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            execution_audit=self.audit,
        )

    def evaluate(self, *, skill_path, clean_test, output_dir, stage):
        self.evaluate_calls.append(stage)
        score = self.seed_score if stage == "seed" else self.clean_score
        scores = {}
        for task in clean_test:
            with self.timing.span(level="task", name=stage, task_id=task.task_id):
                record_token_event(
                    ledger_dir=self.run_dir / "token_usage",
                    context={
                        "run_id": self.run_dir.name,
                        "domain": "document",
                        "benchmark": "fixture",
                        "arm": stage,
                        "stage": "eval",
                    },
                    usage={
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                    },
                    cache_hit=False,
                    billed=True,
                    status="success",
                    source="fixture",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                )
                scores[task.task_id] = score
        return EvaluationResult(
            score=score,
            per_task_scores=scores,
            diagnostics=self.evaluation_diagnostics.get(stage, {}),
        )


def _identity(method_seed: int = 20260813, *, benchmark: str = "fixture"):
    baseline = BaselineFingerprint(
        baseline="fixture",
        repository="https://example.com/fixture.git",
        upstream_revision="1" * 40,
        patch_paths=[],
        patch_hashes=[],
        patchset_hash="2" * 64,
        python_version="3.13.5",
        fingerprint="3" * 64,
    )
    identity = build_experiment_identity(
        ExperimentIdentityInput(
            repository_commit="4" * 40,
            baseline=baseline,
            environment_hash="5" * 64,
            manifest_hash="6" * 64,
            dataset_hashes={"fixture": "7" * 64},
            seed_skill_hash=_hash("seed skill"),
            model="deepseek-v4-flash",
            provider="deepseek",
            runtime={"workers": 1},
            benchmark=benchmark,
            stage="clean",
            method_seed=method_seed,
        )
    )
    return identity, build_attempt_identity(identity, attempt_number=1)


def _run(
    tmp_path: Path,
    executor: FixtureExecutor,
    *,
    policy: CleanQualificationPolicy | None = None,
):
    seed = tmp_path / "seed.md"
    seed.write_text("seed skill", encoding="utf-8")
    identity, attempt = _identity()
    return CleanEvolutionRunner(executor).run(
        method="fixture",
        split=_split(),
        seed_skill_path=seed,
        method_seed=20260813,
        parameters={"model": "deepseek-v4-flash", "thinking": "disabled"},
        output_root=tmp_path / "runs",
        policy=policy or CleanQualificationPolicy(),
        identity=identity,
        attempt=attempt,
    )


def test_clean_runner_executes_one_arm_and_persists_qualification(tmp_path: Path):
    executor = FixtureExecutor()

    result = _run(tmp_path, executor)

    run_dir = Path(result.run_dir)
    assert executor.evaluate_calls == ["seed", "clean"]
    assert [call.arm for call in executor.evolve_calls] == ["clean"]
    assert result.qualification.passed is True
    assert result.qualification.clean_gain == 0.5
    assert result.method_seed == 20260813
    assert result.identity.experiment_id == _identity()[0].experiment_id
    assert result.attempt.experiment_id == result.identity.experiment_id
    assert result.timing.run.level == "run"
    assert {span.name for span in result.timing.stages} == {
        "seed_evaluation",
        "evolution",
        "clean_test_evaluation",
    }
    assert {span.task_id for span in result.timing.tasks} == {"test"}
    assert not (run_dir / "noisy").exists()
    assert "noisy" not in (run_dir / "split_manifest.json").read_text()
    assert (run_dir / "seed/evaluation/result.json").is_file()
    assert (run_dir / "clean/clean_test_evaluation/result.json").is_file()
    assert (run_dir / "qualification.json").is_file()
    assert (run_dir / "result.json").is_file()
    assert (run_dir / "report.md").is_file()
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Clean Baseline Qualification Result")
    assert "Accepted updates | 1" in report
    assert result.token_usage["billed_tokens"]["total_tokens"] == 6
    assert (run_dir / "timing/events.jsonl").is_file()
    assert (run_dir / "timing/summary.json").is_file()


def test_clean_runner_validation_only_uses_evolution_audit_without_evaluation(
    tmp_path: Path,
) -> None:
    def task(task_id: str) -> TaskManifest:
        return TaskManifest(
            task_id=task_id,
            benchmark="skilllearnbench",
            domain="skill_learning",
            prompt=task_id,
            source_hash=_hash(task_id),
            verifier="skilllearn_hidden_test_v1",
            metadata={"task_family": "family"},
        )

    split = CleanEvolutionSplitManifest(
        benchmark="skilllearnbench",
        domain="skill_learning",
        seed=7,
        source_hash=_hash("validation-only"),
        train=[task("train-1"), task("train-2")],
        validation=[task("validation")],
        clean_test=[],
        metadata={
            "qualification_version": "noise-screen-v1",
            "evaluation_mode": "validation_only",
        },
    )
    executor = FixtureExecutor(
        audit=EvolutionExecutionAudit(
            train_task_ids=["train-1", "train-2"],
            validation_task_ids=["validation"],
            accepted_update_count=1,
        )
    )
    seed = tmp_path / "seed.md"
    seed.write_text("seed skill", encoding="utf-8")
    identity, attempt = _identity(benchmark="skilllearnbench")

    result = CleanEvolutionRunner(executor).run(
        method="skilllearn_self_feedback",
        split=split,
        seed_skill_path=seed,
        method_seed=20260813,
        parameters={"model": "deepseek-v4-flash", "thinking": "disabled"},
        output_root=tmp_path / "runs",
        identity=identity,
        attempt=attempt,
    )

    assert executor.evaluate_calls == []
    assert result.seed_evaluation.per_task_scores == {}
    assert result.clean_evaluation.per_task_scores == {}
    assert result.qualification.passed is True
    assert result.qualification.clean_gain == 0


@pytest.mark.parametrize(
    ("executor", "reason"),
    [
        (
            FixtureExecutor(audit=None),
            "missing_execution_audit",
        ),
        (
            FixtureExecutor(
                audit=EvolutionExecutionAudit(
                    train_task_ids=[],
                    validation_task_ids=["validation"],
                    accepted_update_count=1,
                )
            ),
            "train_execution_coverage",
        ),
        (
            FixtureExecutor(
                audit=EvolutionExecutionAudit(
                    train_task_ids=["train"],
                    validation_task_ids=["validation"],
                    accepted_update_count=0,
                )
            ),
            "no_accepted_update",
        ),
        (
            FixtureExecutor(artifact_updated=False),
            "artifact_unchanged",
        ),
        (
            FixtureExecutor(seed_score=0.75, clean_score=0.25),
            "clean_score_decreased",
        ),
    ],
)
def test_clean_runner_returns_typed_failed_qualification(
    tmp_path: Path,
    executor: FixtureExecutor,
    reason: str,
):
    if reason == "missing_execution_audit":
        executor.audit = None

    result = _run(tmp_path, executor)

    assert result.qualification.passed is False
    assert reason in result.qualification.failure_reasons


@pytest.mark.parametrize(
    ("policy", "diagnostics", "reason"),
    [
        (
            CleanQualificationPolicy(min_parseable_answer_rate=0.8),
            {"clean": {"parseable_answer_rate": 0.7}},
            "parseable_answer_rate",
        ),
        (
            CleanQualificationPolicy(max_systemic_failure_rate=0.05),
            {"clean": {"systemic_failure_rate": 0.10}},
            "systemic_failure_rate",
        ),
        (
            CleanQualificationPolicy(),
            {"seed": {"execution_failures": {"test": "provider timeout"}}},
            "execution_failure",
        ),
    ],
)
def test_clean_runner_enforces_runtime_gates(
    tmp_path: Path,
    policy: CleanQualificationPolicy,
    diagnostics: dict[str, dict],
    reason: str,
):
    result = _run(
        tmp_path,
        FixtureExecutor(evaluation_diagnostics=diagnostics),
        policy=policy,
    )

    assert result.qualification.runtime_gates_passed is False
    assert reason in result.qualification.failure_reasons


def test_clean_runner_requires_exact_clean_test_coverage(tmp_path: Path):
    class MissingTestExecutor(FixtureExecutor):
        def evaluate(self, *, skill_path, clean_test, output_dir, stage):
            result = super().evaluate(
                skill_path=skill_path,
                clean_test=clean_test,
                output_dir=output_dir,
                stage=stage,
            )
            return result.model_copy(update={"per_task_scores": {}})

    result = _run(tmp_path, MissingTestExecutor())

    assert result.qualification.execution_coverage_passed is False
    assert "clean_test_execution_coverage" in result.qualification.failure_reasons


def test_clean_runner_persists_operational_failure_before_raising(tmp_path: Path):
    executor = FixtureExecutor(evolve_error=RuntimeError("evolution crashed"))

    with pytest.raises(CleanQualificationRunError) as exc_info:
        _run(tmp_path, executor)

    run_dir = exc_info.value.run_dir
    failure = json.loads((run_dir / "failure.json").read_text(encoding="utf-8"))
    assert failure == {"exception_type": "RuntimeError", "message": "evolution crashed"}
    assert (run_dir / "token_usage/summary.json").is_file()
    timing = json.loads((run_dir / "timing/summary.json").read_text())
    assert timing["run"]["status"] == "failed"
    assert {span["name"] for span in timing["stages"]} == {
        "seed_evaluation",
        "evolution",
    }
    assert timing["stages"][-1]["status"] == "failed"
    assert not (run_dir / "noisy").exists()
