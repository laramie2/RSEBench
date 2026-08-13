"""Stable public interface for RSEBench runtime evidence noise."""

from rsebench.evidence.contracts import (
    EvidenceRecord,
    EvidenceStage,
    FeedbackRecord,
    HookContext,
    MutationAudit,
    MutationResult,
    RuntimeNoiseSpec,
    TraceEvent,
    TraceKind,
    TrajectoryRecord,
)
from rsebench.evidence.io import canonical_hash, canonical_json, read_record, write_record
from rsebench.evidence.hooks import EvidenceAdapter, EvidenceNoiseHook
from rsebench.evidence.operators import (
    mutate_record,
    omit_selected_event,
    replace_feedback_attribution,
)

__all__ = [
    "EvidenceRecord",
    "EvidenceAdapter",
    "EvidenceNoiseHook",
    "EvidenceStage",
    "FeedbackRecord",
    "HookContext",
    "MutationAudit",
    "MutationResult",
    "RuntimeNoiseSpec",
    "TraceEvent",
    "TraceKind",
    "TrajectoryRecord",
    "canonical_hash",
    "canonical_json",
    "read_record",
    "write_record",
    "mutate_record",
    "omit_selected_event",
    "replace_feedback_attribution",
]
