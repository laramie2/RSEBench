import hashlib

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_contracts import (
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
    EvolutionExecutionAudit,
)


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="document",
        prompt=task_id,
        gold_answers=["x"],
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
    )


def test_clean_split_contains_only_clean_tasks_and_rejects_overlap() -> None:
    split = CleanEvolutionSplitManifest(
        benchmark="fixture",
        domain="document",
        seed=7,
        source_hash="a" * 64,
        train=[_task("train")],
        validation=[_task("validation")],
        clean_test=[_task("test")],
        metadata={"config_version": "clean-qualification-v1"},
    )
    payload = split.model_dump(mode="json")
    assert set(payload) == {
        "benchmark",
        "domain",
        "seed",
        "source_hash",
        "train",
        "validation",
        "clean_test",
        "metadata",
    }
    assert "noisy" not in split.model_dump_json()

    with pytest.raises(ValueError, match="must be disjoint"):
        CleanEvolutionSplitManifest(
            benchmark="fixture",
            domain="document",
            seed=7,
            source_hash="a" * 64,
            train=[_task("train")],
            validation=[_task("validation")],
            clean_test=[_task("train")],
        )


def test_execution_audit_requires_unique_exact_task_ids() -> None:
    audit = EvolutionExecutionAudit(
        train_task_ids=["t1", "t2"],
        validation_task_ids=["v1"],
        accepted_update_count=1,
    )
    assert audit.accepted_update_count == 1
    with pytest.raises(ValueError, match="duplicate"):
        EvolutionExecutionAudit(
            train_task_ids=["t1", "t1"],
            validation_task_ids=["v1"],
            accepted_update_count=1,
        )


def test_office_runtime_policy_validates_thresholds() -> None:
    policy = CleanQualificationPolicy(
        min_parseable_answer_rate=0.80,
        max_systemic_failure_rate=0.05,
    )
    assert policy.min_parseable_answer_rate == 0.80
