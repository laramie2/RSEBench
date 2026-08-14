"""Deterministic, fail-closed N3/N4 evidence mutation operators."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from rsebench.evidence.contracts import (
    EvidenceRecord,
    EvidenceStage,
    FeedbackRecord,
    MutationAudit,
    MutationResult,
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
)
from rsebench.evidence.io import canonical_hash


N3_SELECTORS = frozenset({"tag_priority", "oracle_resource_open"})
N4_SELECTORS = frozenset(
    {"same_kind_decoy_event", "same_shape_decoy_resource"}
)


def _stable_rank(seed: int, identifier: str) -> str:
    return hashlib.sha256(f"{seed}:{identifier}".encode("utf-8")).hexdigest()


def _select_by_seed(
    candidates: Iterable[TraceEvent], seed: int
) -> TraceEvent | None:
    eligible = [
        event for event in candidates if not event.metadata.get("protected", False)
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda event: _stable_rank(seed, event.event_id))


def _audit(
    *,
    spec: RuntimeNoiseSpec,
    input_record: EvidenceRecord,
    output_record: EvidenceRecord,
    applicable: bool,
    selected_ids: list[str] | None = None,
    reason: str | None = None,
    before_fragments: dict[str, object] | None = None,
    after_fragments: dict[str, object] | None = None,
) -> MutationAudit:
    return MutationAudit(
        stage=spec.stage,
        operator=spec.operator,
        applicable=applicable,
        input_hash=canonical_hash(input_record),
        output_hash=canonical_hash(output_record),
        selected_ids=selected_ids or [],
        reason=reason,
        before_fragments=before_fragments or {},
        after_fragments=after_fragments or {},
        metadata={
            "benchmark": spec.benchmark,
            "domain": spec.domain,
            "selector": spec.selector,
            "seed": spec.seed,
            "spec_version": spec.version,
        },
    )


def _inapplicable(
    record: EvidenceRecord, spec: RuntimeNoiseSpec, reason: str
) -> MutationResult:
    return MutationResult(
        input_record=record,
        output_record=record,
        audit=_audit(
            spec=spec,
            input_record=record,
            output_record=record,
            applicable=False,
            reason=reason,
        ),
    )


def _tag_priority_event(
    record: TrajectoryRecord, spec: RuntimeNoiseSpec
) -> TraceEvent | None:
    tags = spec.selector_parameters.get("tags", [])
    if not isinstance(tags, list):
        raise ValueError("tag_priority selector requires a tags list")
    for tag in tags:
        selected = _select_by_seed(
            (event for event in record.events if tag in event.tags), spec.seed
        )
        if selected is not None:
            return selected
    return None


def _oracle_resource_event(
    record: TrajectoryRecord, spec: RuntimeNoiseSpec
) -> TraceEvent | None:
    oracle_refs = spec.selector_parameters.get("oracle_resource_refs", [])
    if not isinstance(oracle_refs, list):
        raise ValueError(
            "oracle_resource_open selector requires oracle_resource_refs"
        )
    oracle_set = set(oracle_refs)
    return _select_by_seed(
        (
            event
            for event in record.events
            if oracle_set.intersection(event.resource_refs)
            and (
                "source_open" in event.tags
                or "source_read" in event.tags
                or event.kind.value == "tool"
            )
        ),
        spec.seed,
    )


def omit_selected_event(
    record: TrajectoryRecord, spec: RuntimeNoiseSpec
) -> MutationResult:
    if spec.stage != EvidenceStage.trajectory:
        raise ValueError("event omission requires N3")
    if spec.budget != 1:
        raise ValueError("Core-1 runtime operators currently require budget=1")
    if spec.selector == "tag_priority":
        selected = _tag_priority_event(record, spec)
    elif spec.selector == "oracle_resource_open":
        selected = _oracle_resource_event(record, spec)
    else:
        raise ValueError(f"unsupported N3 selector: {spec.selector}")
    if selected is None:
        return _inapplicable(record, spec, "no eligible event for configured selector")

    output = record.model_copy(
        update={
            "events": [
                event for event in record.events if event.event_id != selected.event_id
            ]
        },
        deep=True,
    )
    return MutationResult(
        input_record=record,
        output_record=output,
        audit=_audit(
            spec=spec,
            input_record=record,
            output_record=output,
            applicable=True,
            selected_ids=[selected.event_id],
            before_fragments={"event": selected.model_dump(mode="json")},
            after_fragments={"event": None},
        ),
    )


def _same_kind_decoy(
    record: FeedbackRecord,
    trajectory: TrajectoryRecord,
    spec: RuntimeNoiseSpec,
) -> tuple[TraceEvent, list[str]] | None:
    by_id = {event.event_id: event for event in trajectory.events}
    blamed = [by_id[event_id] for event_id in record.blamed_event_ids if event_id in by_id]
    if not blamed:
        return None
    blamed_ids = set(record.blamed_event_ids)
    decoy = _select_by_seed(
        (
            event
            for event in trajectory.events
            if event.kind == blamed[0].kind and event.event_id not in blamed_ids
        ),
        spec.seed,
    )
    return (decoy, decoy.resource_refs) if decoy is not None else None


def _same_shape_decoy(
    record: FeedbackRecord,
    trajectory: TrajectoryRecord,
    spec: RuntimeNoiseSpec,
) -> tuple[TraceEvent, list[str]] | None:
    shapes = spec.selector_parameters.get("resource_shapes", {})
    if not isinstance(shapes, dict):
        raise ValueError(
            "same_shape_decoy_resource selector requires resource_shapes"
        )
    targets = record.blamed_resource_refs
    if not targets:
        return None
    target_shape = shapes.get(targets[0])
    if target_shape is None:
        return None
    blamed_refs = set(targets)
    candidates: list[tuple[TraceEvent, str]] = []
    for event in trajectory.events:
        if event.metadata.get("protected", False):
            continue
        for resource_ref in event.resource_refs:
            if resource_ref not in blamed_refs and shapes.get(resource_ref) == target_shape:
                candidates.append((event, resource_ref))
    if not candidates:
        return None
    event, resource_ref = min(
        candidates,
        key=lambda pair: _stable_rank(
            spec.seed, f"{pair[0].event_id}:{pair[1]}"
        ),
    )
    return event, [resource_ref]


def replace_feedback_attribution(
    record: FeedbackRecord,
    spec: RuntimeNoiseSpec,
    trajectory: TrajectoryRecord,
) -> MutationResult:
    if spec.stage != EvidenceStage.feedback:
        raise ValueError("feedback attribution replacement requires N4")
    if spec.budget != 1:
        raise ValueError("Core-1 runtime operators currently require budget=1")
    if record.task_id != trajectory.task_id:
        raise ValueError("feedback and trajectory task IDs must match")
    if spec.selector == "same_kind_decoy_event":
        selected = _same_kind_decoy(record, trajectory, spec)
    elif spec.selector == "same_shape_decoy_resource":
        selected = _same_shape_decoy(record, trajectory, spec)
    else:
        raise ValueError(f"unsupported N4 selector: {spec.selector}")
    if selected is None:
        return _inapplicable(
            record, spec, "no eligible attribution decoy for configured selector"
        )

    event, resource_refs = selected
    diagnosis = spec.selector_parameters.get(
        "replacement_diagnosis",
        f"The first actionable fault is attributed to event {event.event_id}.",
    )
    if not isinstance(diagnosis, str):
        raise ValueError("replacement_diagnosis must be a string")
    output = record.model_copy(
        update={
            "blamed_event_ids": [event.event_id],
            "blamed_resource_refs": resource_refs,
            "diagnosis": diagnosis,
        },
        deep=True,
    )
    before = {
        "blamed_event_ids": record.blamed_event_ids,
        "blamed_resource_refs": record.blamed_resource_refs,
        "diagnosis": record.diagnosis,
    }
    after = {
        "blamed_event_ids": output.blamed_event_ids,
        "blamed_resource_refs": output.blamed_resource_refs,
        "diagnosis": output.diagnosis,
    }
    return MutationResult(
        input_record=record,
        output_record=output,
        audit=_audit(
            spec=spec,
            input_record=record,
            output_record=output,
            applicable=True,
            selected_ids=[event.event_id],
            before_fragments=before,
            after_fragments=after,
        ),
    )


def mutate_record(
    record: EvidenceRecord,
    spec: RuntimeNoiseSpec,
    *,
    trajectory: TrajectoryRecord | None = None,
) -> MutationResult:
    """Apply one configured mutation without operator fallback."""

    if spec.stage == EvidenceStage.trajectory:
        if not isinstance(record, TrajectoryRecord):
            raise ValueError("N3 mutation requires a trajectory record")
        return omit_selected_event(record, spec)
    if not isinstance(record, FeedbackRecord):
        raise ValueError("N4 mutation requires a feedback record")
    if trajectory is None:
        raise ValueError("N4 mutation requires the associated trajectory")
    return replace_feedback_attribution(record, spec, trajectory)

