from __future__ import annotations

import json

import pytest

from rsebench.evidence import (
    FeedbackRecord,
    HookContext,
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
    write_record,
)
from rsebench.evidence.hooks import EvidenceNoiseHook


class DictAdapter:
    def normalize_trajectory(
        self, native: dict[str, object], context: HookContext
    ) -> TrajectoryRecord:
        return TrajectoryRecord.model_validate(native)

    def denormalize_trajectory(
        self,
        native: dict[str, object],
        normalized: TrajectoryRecord,
        context: HookContext,
    ) -> dict[str, object]:
        return normalized.model_dump(mode="json")

    def normalize_feedback(
        self, native: dict[str, object], context: HookContext
    ) -> FeedbackRecord:
        return FeedbackRecord.model_validate(native)

    def denormalize_feedback(
        self,
        native: dict[str, object],
        normalized: FeedbackRecord,
        context: HookContext,
    ) -> dict[str, object]:
        return normalized.model_dump(mode="json")


def native_trajectory() -> dict[str, object]:
    return TrajectoryRecord(
        task_id="task/1",
        benchmark="webshop",
        events=[
            TraceEvent(
                event_id="e0",
                step_index=0,
                kind="action",
                action="search[x]",
                tags=["query_refinement"],
            ),
            TraceEvent(
                event_id="e1",
                step_index=1,
                kind="action",
                action="click[y]",
                tags=["required_option"],
            ),
        ],
        reward=0.0,
        success=False,
    ).model_dump(mode="json")


def context(tmp_path, *, arm: str) -> HookContext:
    return HookContext(
        task_id="task/1",
        benchmark="webshop",
        domain="interactive",
        method="skilladaptor",
        arm=arm,
        run_dir=tmp_path,
    )


def test_identity_hook_returns_same_native_object(tmp_path) -> None:
    native = native_trajectory()
    hook = EvidenceNoiseHook(adapter=DictAdapter())

    output = hook.after_rollout(native, context(tmp_path, arm="clean"))

    assert output is native
    assert not (tmp_path / "mutation_audit").exists()


def test_clean_arm_is_identity_even_when_runtime_specs_are_installed(tmp_path) -> None:
    native = native_trajectory()
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_critical_event",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["required_option"]},
    )
    hook = EvidenceNoiseHook(adapter=DictAdapter(), specs={"N3": spec})

    output = hook.after_rollout(native, context(tmp_path, arm="clean"))

    assert output is native
    assert not (tmp_path / "mutation_audit").exists()


def test_runtime_spec_must_match_hook_context(tmp_path) -> None:
    native = native_trajectory()
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_critical_event",
        benchmark="officeqa_full",
        domain="document",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["required_option"]},
    )
    hook = EvidenceNoiseHook(adapter=DictAdapter(), specs={"N3": spec})

    with pytest.raises(ValueError, match="benchmark mismatch"):
        hook.after_rollout(native, context(tmp_path, arm="noisy"))


def test_noisy_hook_writes_replay_pack(tmp_path) -> None:
    native = native_trajectory()
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_critical_event",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["required_option"]},
    )
    hook = EvidenceNoiseHook(adapter=DictAdapter(), specs={"N3": spec})

    output = hook.after_rollout(native, context(tmp_path, arm="noisy"))

    assert [event["event_id"] for event in output["events"]] == ["e0"]
    replay = tmp_path / "mutation_audit" / "noisy" / "task_1" / "N3"
    assert {path.name for path in replay.iterdir()} == {
        "input.json",
        "output.json",
        "audit.json",
    }
    audit = json.loads((replay / "audit.json").read_text())
    assert audit["applicable"] is True
    assert audit["input_hash"] != audit["output_hash"]


def test_hook_can_load_release_specs_from_files(tmp_path) -> None:
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_critical_event",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["required_option"]},
    )
    spec_path = tmp_path / "N3.json"
    write_record(spec_path, spec)
    hook = EvidenceNoiseHook.from_spec_files(
        adapter=DictAdapter(), spec_paths=[spec_path]
    )

    output = hook.after_rollout(
        native_trajectory(), context(tmp_path, arm="noisy")
    )

    assert [event["event_id"] for event in output["events"]] == ["e0"]


def test_feedback_hook_mutates_after_feedback_only(tmp_path) -> None:
    trajectory = native_trajectory()
    feedback = FeedbackRecord(
        task_id="task/1",
        benchmark="webshop",
        blamed_event_ids=["e1"],
        diagnosis="bad option",
        scalar_reward=0.0,
    ).model_dump(mode="json")
    spec = RuntimeNoiseSpec(
        stage="N4",
        operator="replace_feedback_attribution",
        benchmark="webshop",
        domain="interactive",
        seed=2,
        selector="same_kind_decoy_event",
    )
    hook = EvidenceNoiseHook(adapter=DictAdapter(), specs={"N4": spec})

    output = hook.after_feedback(
        feedback,
        trajectory,
        context(tmp_path, arm="noisy"),
    )

    assert output["blamed_event_ids"] == ["e0"]
    replay = tmp_path / "mutation_audit" / "noisy" / "task_1" / "N4"
    assert (replay / "audit.json").exists()
