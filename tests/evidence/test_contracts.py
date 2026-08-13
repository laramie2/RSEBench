from __future__ import annotations

import json

import pytest

from rsebench.evidence import (
    FeedbackRecord,
    HookContext,
    MutationAudit,
    MutationResult,
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
    canonical_hash,
    read_record,
    write_record,
)


def trajectory() -> TrajectoryRecord:
    return TrajectoryRecord(
        task_id="task-1",
        benchmark="webshop",
        events=[
            TraceEvent(
                event_id="e0",
                step_index=0,
                kind="action",
                action="search[red mug]",
                tags=["query_refinement"],
            )
        ],
        reward=0.5,
        success=False,
    )


def test_runtime_spec_rejects_static_stage() -> None:
    with pytest.raises(ValueError, match="runtime stage"):
        RuntimeNoiseSpec(
            stage="N2",
            operator="x",
            benchmark="b",
            domain="d",
            seed=1,
            selector="tag_priority",
        )


def test_trajectory_event_ids_are_unique() -> None:
    event = TraceEvent(
        event_id="e1", step_index=0, kind="action", action="search[x]"
    )
    with pytest.raises(ValueError, match="unique"):
        TrajectoryRecord(task_id="t", benchmark="b", events=[event, event])


def test_canonical_hash_ignores_mapping_order() -> None:
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash(
        {"b": 2, "a": 1}
    )


def test_record_round_trip_uses_discriminator(tmp_path) -> None:
    path = tmp_path / "record.json"
    write_record(path, trajectory())

    loaded = read_record(path)

    assert isinstance(loaded, TrajectoryRecord)
    assert loaded == trajectory()
    assert json.loads(path.read_text())["record_type"] == "trajectory"


def test_mutation_result_rejects_n3_reward_change() -> None:
    original = trajectory()
    changed = original.model_copy(update={"reward": 0.0})
    audit = MutationAudit(
        stage="N3",
        operator="omit_critical_event",
        applicable=True,
        input_hash=canonical_hash(original),
        output_hash=canonical_hash(changed),
    )

    with pytest.raises(ValueError, match="reward and success"):
        MutationResult(input_record=original, output_record=changed, audit=audit)


def test_mutation_result_rejects_n4_scalar_reward_change() -> None:
    original = FeedbackRecord(
        task_id="task-1",
        benchmark="webshop",
        blamed_event_ids=["e0"],
        diagnosis="wrong query",
        scalar_reward=0.5,
    )
    changed = original.model_copy(update={"scalar_reward": 0.0})
    audit = MutationAudit(
        stage="N4",
        operator="replace_feedback_attribution",
        applicable=True,
        input_hash=canonical_hash(original),
        output_hash=canonical_hash(changed),
    )

    with pytest.raises(ValueError, match="scalar reward"):
        MutationResult(input_record=original, output_record=changed, audit=audit)


def test_context_rejects_unknown_arm() -> None:
    with pytest.raises(ValueError):
        HookContext(
            task_id="t",
            benchmark="b",
            domain="d",
            method="m",
            arm="counterfactual",
            run_dir="/tmp/run",
        )
