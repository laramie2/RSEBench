"""Public normalized records for runtime evolution-evidence noise."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel


class EvidenceStage(str, Enum):
    task_context = "N1"
    environment_evidence = "N2"
    trajectory = "N3"
    feedback = "N4"


class TraceKind(str, Enum):
    action = "action"
    observation = "observation"
    tool = "tool"
    message = "message"


class TraceEvent(StrictModel):
    event_id: str = Field(min_length=1)
    step_index: int = Field(ge=0)
    kind: TraceKind
    action: str | None = None
    observation: str | None = None
    resource_refs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_event_content(self) -> "TraceEvent":
        if not (self.action or self.observation or self.resource_refs):
            raise ValueError(
                "trace event requires action, observation, or resource reference"
            )
        return self


class TrajectoryRecord(StrictModel):
    record_type: Literal["trajectory"] = "trajectory"
    task_id: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    events: list[TraceEvent]
    reward: float | None = None
    success: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_unique_event_ids(self) -> "TrajectoryRecord":
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("trajectory event IDs must be unique")
        return self


class FeedbackRecord(StrictModel):
    record_type: Literal["feedback"] = "feedback"
    task_id: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    blamed_event_ids: list[str] = Field(default_factory=list)
    blamed_resource_refs: list[str] = Field(default_factory=list)
    diagnosis: str = ""
    recommendation: str = ""
    scalar_reward: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


EvidenceRecord = TrajectoryRecord | FeedbackRecord


class RuntimeNoiseSpec(StrictModel):
    schema_version: Literal["rsebench.runtime-noise-spec.v1"] = Field(
        default="rsebench.runtime-noise-spec.v1",
        exclude_if=lambda value: value == "rsebench.runtime-noise-spec.v1",
    )
    stage: EvidenceStage
    operator: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    seed: int
    selector: str = Field(min_length=1)
    selector_parameters: dict[str, Any] = Field(default_factory=dict)
    budget: int = Field(default=1, gt=0)
    protected_fields: list[str] = Field(default_factory=list)
    failure_policy: Literal["record_inapplicable"] = "record_inapplicable"
    version: str = Field(default="v1", min_length=1)

    @model_validator(mode="after")
    def require_runtime_stage(self) -> "RuntimeNoiseSpec":
        if self.stage not in {
            EvidenceStage.trajectory,
            EvidenceStage.feedback,
        }:
            raise ValueError("runtime stage must be N3 or N4")
        return self


class HookContext(StrictModel):
    task_id: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    method: str = Field(min_length=1)
    arm: Literal["clean", "noisy"]
    run_dir: Path
    metadata: dict[str, Any] = Field(default_factory=dict)


class MutationAudit(StrictModel):
    stage: EvidenceStage
    operator: str = Field(min_length=1)
    applicable: bool
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_ids: list[str] = Field(default_factory=list)
    reason: str | None = None
    before_fragments: dict[str, Any] = Field(default_factory=dict)
    after_fragments: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MutationResult(StrictModel):
    input_record: EvidenceRecord = Field(discriminator="record_type")
    output_record: EvidenceRecord = Field(discriminator="record_type")
    audit: MutationAudit

    @model_validator(mode="after")
    def enforce_stage_boundaries(self) -> "MutationResult":
        if type(self.input_record) is not type(self.output_record):
            raise ValueError("mutation cannot change the evidence record type")
        if self.audit.stage == EvidenceStage.trajectory:
            if not isinstance(self.input_record, TrajectoryRecord):
                raise ValueError("N3 requires trajectory records")
            if (
                self.input_record.reward != self.output_record.reward
                or self.input_record.success != self.output_record.success
            ):
                raise ValueError("N3 must preserve reward and success")
        elif self.audit.stage == EvidenceStage.feedback:
            if not isinstance(self.input_record, FeedbackRecord):
                raise ValueError("N4 requires feedback records")
            if self.input_record.scalar_reward != self.output_record.scalar_reward:
                raise ValueError("N4 must preserve scalar reward")
        return self
