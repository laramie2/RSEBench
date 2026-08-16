"""Immutable identities for SkillFlow clean qualification."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from rsebench.contracts import StrictModel


UPSTREAM_REVISION = "7b49ff5a7e26cd7706e959bfa0dba4746d18440d"
REPLICATES = ("r1", "r2", "r3")


class FrozenStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillFlowRuntimeConfig(FrozenStrictModel):
    model: Literal["deepseek-v4-flash"]
    thinking: Literal["disabled"]
    temperature: Literal[0.0]
    max_turns: int = Field(ge=1, le=100)
    max_completion_tokens: int = Field(ge=1)
    patch_temperature: float = Field(ge=0.0)
    patch_max_tokens: int = Field(ge=1)
    patch_max_steps: int = Field(ge=2)
    patch_max_observation_chars: int = Field(ge=1)
    docker_image: str = Field(min_length=1)
    arm_timeout_seconds: int = Field(ge=1)


class SkillFlowQualificationGate(FrozenStrictModel):
    minimum_positive_replicates: Literal[2]
    minimum_nonnegative_replicates: Literal[3]
    minimum_patch_replicates: Literal[3]
    minimum_skill_use_replicates: Literal[2]
    require_positive_pooled_full_delta: Literal[True]
    target_qualified_families: Literal[2]


class SkillFlowCleanConfig(FrozenStrictModel):
    schema_version: Literal["rsebench.skillflow-clean-config.v1"]
    benchmark: Literal["skillflow_tasks"]
    baseline: Literal["skillflow"]
    upstream_revision: Literal[UPSTREAM_REVISION]
    qualification_contract: Literal["skillflow-clean-qualification-v1"]
    data_root: str = Field(min_length=1)
    output_root: str = Field(min_length=1)
    batch_a: list[str] = Field(min_length=1)
    batch_b: list[str]
    replicates: list[Literal["r1", "r2", "r3"]]
    runtime: SkillFlowRuntimeConfig
    qualification: SkillFlowQualificationGate

    @model_validator(mode="after")
    def validate_selection(self) -> "SkillFlowCleanConfig":
        _validate_batches_and_replicates(self.batch_a, self.batch_b, self.replicates)
        return self


class SkillFlowTaskIdentity(FrozenStrictModel):
    task_id: str = Field(min_length=1)
    order: int = Field(ge=1)
    relative_path: str = Field(min_length=1)
    task_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 2:
            raise ValueError("SkillFlow task path must be family/task relative")
        if any(not part or part in {".", ".."} for part in path.parts):
            raise ValueError("SkillFlow task path contains an empty component")
        return value


class SkillFlowFamilyManifest(FrozenStrictModel):
    family: str = Field(min_length=1)
    status: Literal["ready", "invalid"]
    ranking_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ranked_task_ids: list[str] = Field(min_length=1)
    tasks: list[SkillFlowTaskIdentity] = Field(min_length=1)
    invalid_reasons: list[str]

    @model_validator(mode="after")
    def validate_tasks(self) -> "SkillFlowFamilyManifest":
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("SkillFlow family task IDs must be unique")
        if len(self.ranked_task_ids) != len(set(self.ranked_task_ids)):
            raise ValueError("SkillFlow ranked task IDs must be unique")
        orders = [task.order for task in self.tasks]
        if len(orders) != len(set(orders)) or orders != sorted(orders):
            raise ValueError("SkillFlow family task order must be unique and increasing")
        expected_prefix = f"{self.family}/"
        if any(not task.relative_path.startswith(expected_prefix) for task in self.tasks):
            raise ValueError("SkillFlow task path belongs to a different family")
        if any(PurePosixPath(task.relative_path).name != task.task_id for task in self.tasks):
            raise ValueError("SkillFlow task ID differs from its relative path")
        if self.status == "ready":
            if self.invalid_reasons:
                raise ValueError("ready SkillFlow family cannot have invalid reasons")
            if ids != self.ranked_task_ids:
                raise ValueError("ready SkillFlow family tasks must equal ranking")
            if orders != list(range(1, len(self.tasks) + 1)):
                raise ValueError("ready SkillFlow family order must be contiguous")
        elif not self.invalid_reasons:
            raise ValueError("invalid SkillFlow family requires typed reasons")
        return self


class SkillFlowInputManifest(FrozenStrictModel):
    schema_version: Literal["rsebench.skillflow-input.v1"]
    benchmark: Literal["skillflow_tasks"]
    baseline: Literal["skillflow"]
    upstream_revision: Literal[UPSTREAM_REVISION]
    qualification_contract: Literal["skillflow-clean-qualification-v1"]
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime: SkillFlowRuntimeConfig
    qualification: SkillFlowQualificationGate
    batch_a: list[str] = Field(min_length=1)
    batch_b: list[str]
    replicates: list[Literal["r1", "r2", "r3"]]
    families: list[SkillFlowFamilyManifest] = Field(min_length=1)
    provider_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_identity(self) -> "SkillFlowInputManifest":
        _validate_batches_and_replicates(self.batch_a, self.batch_b, self.replicates)
        family_names = [family.family for family in self.families]
        expected = [*self.batch_a, *self.batch_b]
        if family_names != expected:
            raise ValueError("SkillFlow manifest families differ from candidate order")
        return self


def _validate_batches_and_replicates(
    batch_a: list[str], batch_b: list[str], replicates: list[str]
) -> None:
    families = [*batch_a, *batch_b]
    if any(not family.strip() for family in families):
        raise ValueError("SkillFlow family names must not be empty")
    if len(families) != len(set(families)):
        raise ValueError("SkillFlow candidate families must be unique")
    if tuple(replicates) != REPLICATES:
        raise ValueError("SkillFlow replicates must be exactly r1/r2/r3")


__all__ = [
    "REPLICATES",
    "UPSTREAM_REVISION",
    "FrozenStrictModel",
    "SkillFlowCleanConfig",
    "SkillFlowFamilyManifest",
    "SkillFlowInputManifest",
    "SkillFlowQualificationGate",
    "SkillFlowRuntimeConfig",
    "SkillFlowTaskIdentity",
]
