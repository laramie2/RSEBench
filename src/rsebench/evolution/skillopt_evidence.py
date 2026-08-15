"""Normalize SkillOpt conversations at the N3/N4 reflection boundaries."""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

from openpyxl.utils.cell import range_boundaries

from rsebench.evidence import (
    EvidenceNoiseHook,
    EvidenceStage,
    FeedbackRecord,
    HookContext,
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
)


_CELL_REF_RE = re.compile(
    r"(?:(?:[A-Za-z0-9 _()'-]+)!)?[A-Z]{1,3}\d+(?::[A-Z]{1,3}\d+)?"
)
_PATH_RE = re.compile(r"(?:/[^\s'\"(),]+)+\.[A-Za-z0-9]{1,8}")


def _text(item: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get(key) or "")
        for key in ("cmd", "obs", "action", "env_feedback", "content")
    ).strip()


def _resource_refs(text: str) -> list[str]:
    refs = set(_CELL_REF_RE.findall(text))
    for match in _PATH_RE.findall(text):
        refs.add(match)
        refs.add(Path(match).name)
    return sorted(refs)


def _event_tags(item: dict[str, Any], text: str) -> list[str]:
    lower = text.casefold()
    tags: set[str] = set()
    if (
        ("wb.save" in lower or "workbook.save" in lower)
        and (
            "ws[" in lower
            or ".cell(" in lower
            or ".value" in lower
            or "append(" in lower
        )
    ):
        tags.add("workbook_write")
    if item.get("type") == "tool_call" and any(
        token in lower for token in ("read(", "grep(", "open(", "search(")
    ):
        tags.add("source_read")
    if item.get("type") == "tool_call" and any(
        token in lower
        for token in ("write(", "apply_patch", "mkdir", "cp ", "mv ")
    ):
        tags.update({"filesystem_change", "artifact_write"})
    if item.get("role") == "system" and "verification" in lower:
        tags.add("verification")
    return sorted(tags)


class SkillOptEvidenceAdapter:
    def normalize_trajectory(
        self, native: list[dict[str, Any]], context: HookContext
    ) -> TrajectoryRecord:
        events: list[TraceEvent] = []
        for index, item in enumerate(native):
            rendered = _text(item)
            if not rendered:
                continue
            item_type = item.get("type")
            role = item.get("role")
            if item_type == "tool_call":
                kind = "tool"
                action = str(item.get("cmd") or "")
                observation = str(item.get("obs") or "")
            elif role == "assistant" or "action" in item:
                kind = "action"
                action = str(item.get("action") or item.get("content") or "")
                observation = str(item.get("env_feedback") or "") or None
            else:
                kind = "message"
                action = None
                observation = rendered
            protected = bool(role in {"user", "system"})
            events.append(
                TraceEvent(
                    event_id=f"native-{index}",
                    step_index=index,
                    kind=kind,
                    action=action,
                    observation=observation,
                    resource_refs=_resource_refs(rendered),
                    tags=_event_tags(item, rendered),
                    metadata={"native_index": index, "protected": protected},
                )
            )
        return TrajectoryRecord(
            task_id=context.task_id,
            benchmark=context.benchmark,
            events=events,
            metadata={"native_length": len(native), "method": "skillopt"},
        )

    def denormalize_trajectory(
        self,
        native: list[dict[str, Any]],
        normalized: TrajectoryRecord,
        context: HookContext,
    ) -> list[dict[str, Any]]:
        retained = {
            int(event.metadata["native_index"])
            for event in normalized.events
            if "native_index" in event.metadata
        }
        return [copy.deepcopy(item) for index, item in enumerate(native) if index in retained]

    def normalize_feedback(
        self, native: dict[str, Any], context: HookContext
    ) -> FeedbackRecord:
        diagnosis = str(native.get("fail_reason") or "")
        resources = _resource_refs(diagnosis)
        if not resources:
            source_files = native.get("source_files", [])
            if isinstance(source_files, list):
                resources = [str(value) for value in source_files if str(value)]
        return FeedbackRecord(
            task_id=context.task_id,
            benchmark=context.benchmark,
            # Preserve path aliases together so the same physical source cannot
            # be selected as its own N4 decoy via basename/full-path spelling.
            blamed_resource_refs=resources,
            diagnosis=diagnosis,
            scalar_reward=(
                float(native["soft"])
                if isinstance(native.get("soft"), (int, float))
                else None
            ),
            metadata={
                "hard": native.get("hard"),
                "soft": native.get("soft"),
            },
        )

    def denormalize_feedback(
        self,
        native: dict[str, Any],
        normalized: FeedbackRecord,
        context: HookContext,
    ) -> dict[str, Any]:
        output = copy.deepcopy(native)
        output["fail_reason"] = normalized.diagnosis
        return output


def _resource_shape(resource_ref: str) -> str:
    cell_range = resource_ref.rsplit("!", 1)[-1]
    try:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
    except ValueError:
        return "document"
    return f"{max_row - min_row + 1}x{max_col - min_col + 1}"


def _enrich_n4_spec(
    spec: RuntimeNoiseSpec,
    feedback: dict[str, Any],
    conversation: list[dict[str, Any]],
    context: HookContext,
) -> RuntimeNoiseSpec:
    adapter = SkillOptEvidenceAdapter()
    trajectory = adapter.normalize_trajectory(conversation, context)
    normalized_feedback = adapter.normalize_feedback(feedback, context)
    parameters = copy.deepcopy(spec.selector_parameters)
    if spec.selector == "same_shape_decoy_resource":
        all_refs = set(normalized_feedback.blamed_resource_refs)
        all_refs.update(
            ref for event in trajectory.events for ref in event.resource_refs
        )
        parameters.setdefault(
            "resource_shapes", {ref: _resource_shape(ref) for ref in sorted(all_refs)}
        )
    return spec.model_copy(update={"selector_parameters": parameters}, deep=True)


def _enrich_n3_spec(
    spec: RuntimeNoiseSpec, item: dict[str, Any]
) -> RuntimeNoiseSpec:
    """Bind benchmark-owned oracle identities to the generic N3 selector.

    Runtime specs are portable and therefore cannot contain task-specific file
    names. SkillOpt's native OfficeQA item does contain those names, so the
    adapter resolves them at the hook boundary without exposing answer text.
    """

    if spec.selector != "oracle_resource_open":
        return spec
    parameters = copy.deepcopy(spec.selector_parameters)
    refs: set[str] = set()
    for key in ("source_files", "gold_document_ids"):
        values = item.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            rendered = str(value).strip()
            if rendered:
                refs.update({rendered, Path(rendered).name})
    if refs:
        parameters["oracle_resource_refs"] = sorted(refs)
    return spec.model_copy(update={"selector_parameters": parameters}, deep=True)


def mutate_skillopt_conversation(
    conversation: list[dict[str, Any]],
    *,
    spec: RuntimeNoiseSpec | None,
    context: HookContext,
) -> list[dict[str, Any]]:
    if spec is None:
        return conversation
    if spec.stage != EvidenceStage.trajectory:
        return conversation
    hook = EvidenceNoiseHook(
        adapter=SkillOptEvidenceAdapter(), specs={EvidenceStage.trajectory: spec}
    )
    return hook.after_rollout(conversation, context)


def mutate_skillopt_feedback_item(
    item: dict[str, Any],
    conversation: list[dict[str, Any]],
    *,
    spec: RuntimeNoiseSpec | None,
    context: HookContext,
) -> dict[str, Any]:
    if spec is None:
        return item
    if spec.stage != EvidenceStage.feedback:
        return item
    enriched = _enrich_n4_spec(spec, item, conversation, context)
    hook = EvidenceNoiseHook(
        adapter=SkillOptEvidenceAdapter(), specs={EvidenceStage.feedback: enriched}
    )
    return hook.after_feedback(item, conversation, context)


def apply_skillopt_evidence_from_env(
    conversation: list[dict[str, Any]], item: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Optional external-checkout entry point; identity when env is unset."""

    spec_path = os.environ.get("RSEBENCH_EVIDENCE_SPEC", "").strip()
    if not spec_path:
        return conversation, item
    spec = RuntimeNoiseSpec.model_validate(
        json.loads(Path(spec_path).read_text(encoding="utf-8"))
    )
    audit_root = os.environ.get("RSEBENCH_EVIDENCE_AUDIT_ROOT", "").strip()
    if not audit_root:
        raise ValueError(
            "RSEBENCH_EVIDENCE_AUDIT_ROOT is required with RSEBENCH_EVIDENCE_SPEC"
        )
    context = HookContext(
        task_id=str(item["id"]),
        benchmark=spec.benchmark,
        domain=spec.domain,
        method="skillopt",
        arm=os.environ.get("RSEBENCH_EVIDENCE_ARM", "noisy"),
        run_dir=Path(audit_root),
    )
    if spec.stage == EvidenceStage.trajectory:
        enriched = _enrich_n3_spec(spec, item)
        return (
            mutate_skillopt_conversation(
                conversation, spec=enriched, context=context
            ),
            item,
        )
    return (
        conversation,
        mutate_skillopt_feedback_item(
            item, conversation, spec=spec, context=context
        ),
    )
