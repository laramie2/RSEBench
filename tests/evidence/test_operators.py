from __future__ import annotations

from rsebench.evidence import (
    FeedbackRecord,
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
)
from rsebench.evidence.operators import mutate_record


def webshop_trajectory() -> TrajectoryRecord:
    return TrajectoryRecord(
        task_id="ws-1",
        benchmark="webshop",
        events=[
            TraceEvent(
                event_id="e0",
                step_index=0,
                kind="action",
                action="search[red mug]",
                tags=["query_refinement"],
            ),
            TraceEvent(
                event_id="e1",
                step_index=1,
                kind="action",
                action="click[large]",
                tags=["required_option"],
            ),
            TraceEvent(
                event_id="e2",
                step_index=2,
                kind="action",
                action="click[buy now]",
                tags=["purchase"],
            ),
        ],
        reward=0.25,
        success=False,
    )


def test_n3_omits_one_ranked_event_and_preserves_reward() -> None:
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_critical_event",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["required_option", "query_refinement"]},
    )

    result = mutate_record(webshop_trajectory(), spec)

    assert [event.event_id for event in result.output_record.events] == [
        "e0",
        "e2",
    ]
    assert result.output_record.reward == result.input_record.reward
    assert result.output_record.success == result.input_record.success
    assert result.audit.selected_ids == ["e1"]
    assert result.audit.applicable


def test_n3_oracle_selector_omits_only_oracle_open() -> None:
    trajectory = TrajectoryRecord(
        task_id="office-1",
        benchmark="officeqa",
        events=[
            TraceEvent(
                event_id="e0",
                step_index=0,
                kind="tool",
                action="open treasury-2025.pdf",
                resource_refs=["treasury-2025.pdf"],
                tags=["source_open"],
            ),
            TraceEvent(
                event_id="e1",
                step_index=1,
                kind="tool",
                action="open treasury-2024.pdf",
                resource_refs=["treasury-2024.pdf"],
                tags=["source_open"],
            ),
        ],
        reward=1.0,
        success=True,
    )
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_oracle_source_event",
        benchmark="officeqa",
        domain="document_qa",
        seed=11,
        selector="oracle_resource_open",
        selector_parameters={"oracle_resource_refs": ["treasury-2025.pdf"]},
    )

    result = mutate_record(trajectory, spec)

    assert result.audit.selected_ids == ["e0"]
    assert [event.event_id for event in result.output_record.events] == ["e1"]


def test_n4_replaces_blame_with_same_kind_decoy() -> None:
    feedback = FeedbackRecord(
        task_id="ws-1",
        benchmark="webshop",
        blamed_event_ids=["e1"],
        diagnosis="The required size option was handled incorrectly.",
        recommendation="Check hard constraints before buying.",
        scalar_reward=0.25,
    )
    spec = RuntimeNoiseSpec(
        stage="N4",
        operator="replace_feedback_attribution",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="same_kind_decoy_event",
        selector_parameters={
            "replacement_diagnosis": "The purchase action was the first fault."
        },
    )

    result = mutate_record(feedback, spec, trajectory=webshop_trajectory())

    assert result.output_record.blamed_event_ids != ["e1"]
    assert result.output_record.scalar_reward == result.input_record.scalar_reward
    assert result.output_record.diagnosis == "The purchase action was the first fault."
    assert result.audit.before_fragments["blamed_event_ids"] == ["e1"]
    assert result.audit.selected_ids == result.output_record.blamed_event_ids


def test_n4_replaces_resource_with_same_shape_decoy() -> None:
    trajectory = TrajectoryRecord(
        task_id="sheet-1",
        benchmark="spreadsheetbench_verified",
        events=[
            TraceEvent(
                event_id="e0",
                step_index=0,
                kind="tool",
                action="edit Summary!B2:B9",
                resource_refs=["Summary!B2:B9"],
            ),
            TraceEvent(
                event_id="e1",
                step_index=1,
                kind="tool",
                action="edit Archive!B2:B9",
                resource_refs=["Archive!B2:B9"],
            ),
        ],
        reward=0.0,
        success=False,
    )
    feedback = FeedbackRecord(
        task_id="sheet-1",
        benchmark="spreadsheetbench_verified",
        blamed_event_ids=["e0"],
        blamed_resource_refs=["Summary!B2:B9"],
        diagnosis="Summary range is incorrect.",
        scalar_reward=0.0,
    )
    spec = RuntimeNoiseSpec(
        stage="N4",
        operator="replace_feedback_attribution",
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        seed=3,
        selector="same_shape_decoy_resource",
        selector_parameters={
            "resource_shapes": {
                "Summary!B2:B9": "8x1",
                "Archive!B2:B9": "8x1",
            }
        },
    )

    result = mutate_record(feedback, spec, trajectory=trajectory)

    assert result.output_record.blamed_resource_refs == ["Archive!B2:B9"]
    assert result.output_record.blamed_event_ids == ["e1"]


def test_inapplicable_operator_is_identity_without_fallback() -> None:
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_critical_event",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["filesystem_change"]},
    )

    result = mutate_record(webshop_trajectory(), spec)

    assert not result.audit.applicable
    assert result.input_record == result.output_record
    assert result.audit.selected_ids == []
    assert "eligible" in (result.audit.reason or "")


def test_operator_is_deterministic() -> None:
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_critical_event",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["required_option"]},
    )

    first = mutate_record(webshop_trajectory(), spec)
    second = mutate_record(webshop_trajectory(), spec)

    assert first == second
