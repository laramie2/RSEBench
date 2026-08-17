"""Stable stage-owned contracts for static and runtime noise plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from rsebench.contracts import TaskManifest
from rsebench.datasets.contracts import FrozenStrictModel
from rsebench.evidence import (
    FeedbackRecord,
    HookContext,
    MutationResult,
    RuntimeNoiseSpec,
    TrajectoryRecord,
)


NoiseStage = Literal["N1", "N2", "N3", "N4"]
NoiseForm = Literal["static", "runtime"]
StaticStage = Literal["N1", "N2"]
RuntimeStage = Literal["N3", "N4"]
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class StaticNoiseSpec(FrozenStrictModel):
    """One deterministic N1/N2 materialization request."""

    stage: StaticStage
    operator: str = Field(min_length=1)
    version: str = Field(min_length=1)
    dataset_release_id: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    seed: int
    severity: Literal["L0", "L1", "L2", "L3"] = "L2"
    parameters: dict[str, Any] = Field(default_factory=dict)
    protected_fields: tuple[str, ...] = ()


class StaticNoiseResult(FrozenStrictModel):
    """Content-addressed output and fail-closed audit for one static task."""

    stage: StaticStage
    operator: str = Field(min_length=1)
    version: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    seed: int
    applicable: bool
    clean_hash: str = Field(pattern=_HASH_PATTERN)
    noisy_hash: str = Field(pattern=_HASH_PATTERN)
    noisy_uri: str | None = None
    protected_field_audit: dict[str, bool] = Field(default_factory=dict)
    changes: tuple[str, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def enforce_fail_closed_audit(self) -> "StaticNoiseResult":
        if self.applicable:
            if self.clean_hash == self.noisy_hash:
                raise ValueError("applicable static noise must change content hash")
            if not self.noisy_uri:
                raise ValueError("applicable static noise requires a portable noisy URI")
            if not self.changes:
                raise ValueError("applicable static noise requires a change description")
            if not self.protected_field_audit or not all(
                self.protected_field_audit.values()
            ):
                raise ValueError("applicable static noise failed protected-field audit")
        elif not self.reason:
            raise ValueError("inapplicable static noise requires a reason")
        return self


class NoisePlugin(FrozenStrictModel):
    """One top-level package owned independently by a noise-stage collaborator."""

    schema_version: Literal["rsebench.noise-plugin.v1"] = (
        "rsebench.noise-plugin.v1"
    )
    stage: NoiseStage
    form: NoiseForm
    entrypoint: str = Field(min_length=3)
    version: str = Field(min_length=1)
    operators_root: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def stage_matches_form(self) -> "NoisePlugin":
        if ":" not in self.entrypoint:
            raise ValueError("noise plugin entrypoint must use module:attribute")
        if self.form == "runtime" and self.stage not in {"N3", "N4"}:
            raise ValueError("runtime operator requires N3 or N4")
        if self.form == "static" and self.stage not in {"N1", "N2"}:
            raise ValueError("static operator requires N1 or N2")
        return self


class StaticNoiseOperator(Protocol):
    stage: StaticStage

    def materialize(
        self,
        task: TaskManifest,
        spec: StaticNoiseSpec,
        output_dir: Path,
    ) -> StaticNoiseResult: ...


class MethodEvidenceAdapter(Protocol):
    """Normalize and restore method-native evidence at N3/N4 boundaries."""

    def normalize_trajectory(
        self, native: Any, context: HookContext
    ) -> TrajectoryRecord: ...

    def denormalize_trajectory(
        self,
        native: Any,
        normalized: TrajectoryRecord,
        context: HookContext,
    ) -> Any: ...

    def normalize_feedback(
        self, native: Any, context: HookContext
    ) -> FeedbackRecord: ...

    def denormalize_feedback(
        self,
        native: Any,
        normalized: FeedbackRecord,
        context: HookContext,
    ) -> Any: ...


class RuntimeNoiseOperator(Protocol):
    stage: RuntimeStage

    def mutate(
        self,
        record: TrajectoryRecord | FeedbackRecord,
        spec: RuntimeNoiseSpec,
        *,
        trajectory: TrajectoryRecord | None = None,
    ) -> MutationResult: ...


__all__ = [
    "MethodEvidenceAdapter",
    "NoiseForm",
    "NoisePlugin",
    "NoiseStage",
    "RuntimeNoiseOperator",
    "RuntimeStage",
    "StaticNoiseOperator",
    "StaticNoiseResult",
    "StaticNoiseSpec",
    "StaticStage",
]
