"""SkillAdaptor's native WebShop N3/N4 evidence boundary.

The public adapter deliberately uses SkillAdaptor's dataclass-shaped objects
without importing the external checkout. This keeps the benchmark package
installable on its own while still returning native ``Trajectory`` and
``LocalizedFault`` instances when the checkout calls the hook.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

from rsebench.evidence import (
    EvidenceNoiseHook,
    EvidenceStage,
    FeedbackRecord,
    HookContext,
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
)


_ACTION_RE = re.compile(r"^\s*([a-zA-Z_]+)\[(.*)]\s*$")
_RESERVED_CLICKS = {
    "buy now",
    "next >",
    "< prev",
    "back to search",
    "search",
    "description",
    "features",
    "reviews",
}


def _action_tags(action: str, task_description: str) -> list[str]:
    match = _ACTION_RE.match(action)
    if match is None:
        return []
    verb, argument = match.group(1).casefold(), match.group(2).strip().casefold()
    if verb == "search":
        return ["query_refinement"]
    if verb != "click" or argument in _RESERVED_CLICKS:
        return []
    # Product identifiers are navigation, not option selection. WebShop ASINs
    # are ten alphanumeric characters and normally start with B0.
    if re.fullmatch(r"[a-z0-9]{10}", argument) and argument.startswith("b0"):
        return []
    goal = task_description.casefold()
    if argument and argument in goal:
        return ["required_option"]
    return []


class SkillAdaptorEvidenceAdapter:
    """Round-trip native SkillAdaptor records with step-level consistency."""

    def __init__(self, *, trajectory: Any | None = None) -> None:
        self.trajectory = trajectory

    def normalize_trajectory(
        self, native: Any, context: HookContext
    ) -> TrajectoryRecord:
        events = [
            TraceEvent(
                event_id=f"step-{position}",
                step_index=position,
                kind="action",
                action=str(step.action),
                observation=str(step.observation),
                tags=_action_tags(str(step.action), str(native.task_description)),
                metadata={
                    "native_position": position,
                    "native_step_index": int(step.index),
                },
            )
            for position, step in enumerate(native.steps)
        ]
        return TrajectoryRecord(
            task_id=str(native.task_id),
            benchmark=context.benchmark,
            events=events,
            reward=float(native.total_reward),
            success=bool(native.success),
            metadata={
                "method": "skilladaptor",
                "task_description": str(native.task_description),
            },
        )

    def denormalize_trajectory(
        self,
        native: Any,
        normalized: TrajectoryRecord,
        context: HookContext,
    ) -> Any:
        output = copy.deepcopy(native)
        retained_positions = [
            int(event.metadata["native_position"])
            for event in normalized.events
            if "native_position" in event.metadata
        ]
        output.steps = [copy.deepcopy(native.steps[pos]) for pos in retained_positions]
        for new_index, step in enumerate(output.steps):
            step.index = new_index
        if native.error_step is None:
            output.error_step = None
        elif native.error_step in retained_positions:
            output.error_step = retained_positions.index(native.error_step)
        else:
            output.error_step = None
        # The public N3 contract protects these fields. Assign from the
        # normalized record so a broken adapter cannot silently change them.
        output.total_reward = normalized.reward
        output.success = normalized.success
        return output

    def normalize_feedback(
        self, native: Any, context: HookContext
    ) -> FeedbackRecord:
        trajectory = self._require_trajectory()
        position = int(native.step_index)
        blamed = [f"step-{position}"] if 0 <= position < len(trajectory.steps) else []
        return FeedbackRecord(
            task_id=str(native.task_id),
            benchmark=context.benchmark,
            blamed_event_ids=blamed,
            diagnosis=str(native.improvement_principle),
            scalar_reward=float(trajectory.total_reward),
            metadata={
                "fault_type": getattr(native.fault_type, "value", str(native.fault_type)),
                "original_step_index": position,
            },
        )

    def denormalize_feedback(
        self,
        native: Any,
        normalized: FeedbackRecord,
        context: HookContext,
    ) -> Any:
        output = copy.deepcopy(native)
        if not normalized.blamed_event_ids:
            return output
        match = re.fullmatch(r"step-(\d+)", normalized.blamed_event_ids[0])
        if match is None:
            raise ValueError("SkillAdaptor N4 requires step-<position> event IDs")
        position = int(match.group(1))
        trajectory = self._require_trajectory()
        if position < 0 or position >= len(trajectory.steps):
            raise ValueError(f"SkillAdaptor N4 selected invalid step position: {position}")
        step = trajectory.steps[position]
        output.step_index = position
        output.observation = str(step.observation)
        output.wrong_action = str(step.action)
        output.skills_at_fault = list(step.skills_used)
        output.fault_chain = [position + 1]
        output.improvement_principle = normalized.diagnosis
        return output

    def _require_trajectory(self) -> Any:
        if self.trajectory is None:
            raise ValueError("SkillAdaptor feedback adaptation requires its trajectory")
        return self.trajectory


def mutate_skilladaptor_trajectory(
    trajectory: Any,
    *,
    spec: RuntimeNoiseSpec | None,
    context: HookContext,
) -> Any:
    if spec is None or spec.stage != EvidenceStage.trajectory:
        return trajectory
    hook = EvidenceNoiseHook(
        adapter=SkillAdaptorEvidenceAdapter(trajectory=trajectory),
        specs={EvidenceStage.trajectory: spec},
    )
    return hook.after_rollout(trajectory, context)


def mutate_skilladaptor_fault(
    fault: Any,
    trajectory: Any,
    *,
    spec: RuntimeNoiseSpec | None,
    context: HookContext,
) -> Any:
    if spec is None or spec.stage != EvidenceStage.feedback:
        return fault
    hook = EvidenceNoiseHook(
        adapter=SkillAdaptorEvidenceAdapter(trajectory=trajectory),
        specs={EvidenceStage.feedback: spec},
    )
    return hook.after_feedback(fault, trajectory, context)


def _spec_and_context(task_id: str) -> tuple[RuntimeNoiseSpec, HookContext] | None:
    spec_path = os.environ.get("RSEBENCH_EVIDENCE_SPEC", "").strip()
    if not spec_path:
        return None
    spec = RuntimeNoiseSpec.model_validate(
        json.loads(Path(spec_path).read_text(encoding="utf-8"))
    )
    audit_root = os.environ.get("RSEBENCH_EVIDENCE_AUDIT_ROOT", "").strip()
    if not audit_root:
        raise ValueError(
            "RSEBENCH_EVIDENCE_AUDIT_ROOT is required with RSEBENCH_EVIDENCE_SPEC"
        )
    context = HookContext(
        task_id=task_id,
        benchmark=spec.benchmark,
        domain=spec.domain,
        method="skilladaptor",
        arm=os.environ.get("RSEBENCH_EVIDENCE_ARM", "noisy"),
        run_dir=Path(audit_root),
    )
    return spec, context


def apply_skilladaptor_trajectory_from_env(trajectory: Any) -> Any:
    """External-checkout hook immediately after rollout, before Localizer."""

    configured = _spec_and_context(str(trajectory.task_id))
    if configured is None:
        return trajectory
    spec, context = configured
    return mutate_skilladaptor_trajectory(trajectory, spec=spec, context=context)


def apply_skilladaptor_fault_from_env(fault: Any, trajectory: Any) -> Any:
    """External-checkout hook after Localizer, before Linker/Reviser."""

    configured = _spec_and_context(str(trajectory.task_id))
    if configured is None:
        return fault
    spec, context = configured
    return mutate_skilladaptor_fault(
        fault, trajectory, spec=spec, context=context
    )
