"""Immutable contracts for the frozen four-domain validation matrix."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from rsebench.datasets import EvidenceReference
from rsebench.datasets.contracts import FrozenStrictModel
from rsebench.evidence import canonical_hash
from rsebench.noise.contracts import NoiseForm, NoiseStage


ValidationDomain = Literal["spreadsheet", "document", "interactive", "skill"]
SourceMode = Literal["read_only", "copy_on_run"]
_DOMAINS = ("spreadsheet", "document", "interactive", "skill")
_STAGES = ("N1", "N2", "N3", "N4")
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class ValidationProvider(FrozenStrictModel):
    family: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = 0.0
    thinking: Literal["disabled"] = "disabled"


class ValidationExecution(FrozenStrictModel):
    cell_parallelism: int = Field(ge=1, le=16)
    seed_parallelism: int = Field(ge=1)


class ValidationMatrix(FrozenStrictModel):
    schema_version: Literal["rsebench.validation-matrix.v1"] = (
        "rsebench.validation-matrix.v1"
    )
    release_id: str = Field(min_length=1)
    datasets: dict[ValidationDomain, str]
    methods: dict[ValidationDomain, str]
    stages: tuple[NoiseStage, ...]
    operators: dict[ValidationDomain, dict[NoiseStage, str]]
    runtime: dict[ValidationDomain, dict[str, Any]]
    source_modes: dict[ValidationDomain, SourceMode]
    provider: ValidationProvider
    noise_seed: int
    execution: ValidationExecution
    content_hash: str = Field(pattern=_HASH_PATTERN)

    @field_validator("stages", mode="before")
    @classmethod
    def normalize_stages(cls, value: Sequence[str]) -> tuple[str, ...]:
        return tuple(value)

    @model_validator(mode="after")
    def validate_exact_matrix(self) -> "ValidationMatrix":
        for name, mapping in (
            ("datasets", self.datasets),
            ("methods", self.methods),
            ("operators", self.operators),
            ("runtime", self.runtime),
            ("source_modes", self.source_modes),
        ):
            if tuple(mapping) != _DOMAINS:
                raise ValueError(f"{name} must declare the four domains in order")
        if self.stages != _STAGES:
            raise ValueError("validation stages must be exactly N1, N2, N3, N4")
        for domain, operators in self.operators.items():
            if tuple(operators) != _STAGES:
                raise ValueError(f"operators for {domain} must declare N1-N4 in order")
            if any(not value for value in operators.values()):
                raise ValueError(f"operators for {domain} contain an empty identity")
        if self.execution.cell_parallelism != 16:
            raise ValueError("validation-v1 requires cell_parallelism=16")
        if self.execution.seed_parallelism != 1:
            raise ValueError("validation-v1 requires seed_parallelism=1")
        expected = canonical_hash(
            self.model_dump(mode="json", exclude={"content_hash"})
        )
        if self.content_hash != expected:
            raise ValueError(
                f"validation matrix content hash differs: {self.content_hash} != {expected}"
            )
        return self


class ValidationCell(FrozenStrictModel):
    schema_version: Literal["rsebench.validation-cell.v1"] = (
        "rsebench.validation-cell.v1"
    )
    matrix_release_id: str = Field(min_length=1)
    matrix_hash: str = Field(pattern=_HASH_PATTERN)
    cell_id: str = Field(min_length=1)
    identity_hash: str = Field(pattern=_HASH_PATTERN)
    domain: ValidationDomain
    stage: NoiseStage
    form: NoiseForm
    arm: Literal["noisy"] = "noisy"
    operator: str = Field(min_length=1)
    plugin_entrypoint: str = Field(min_length=1)
    plugin_version: str = Field(min_length=1)
    dataset_release_id: str = Field(min_length=1)
    dataset_release_hash: str = Field(pattern=_HASH_PATTERN)
    method_release_id: str = Field(min_length=1)
    method_release_hash: str = Field(pattern=_HASH_PATTERN)
    baseline_fingerprint: str = Field(pattern=_HASH_PATTERN)
    clean_evidence: tuple[EvidenceReference, ...]
    clean_evidence_hash: str = Field(pattern=_HASH_PATTERN)
    provider: ValidationProvider
    runtime: dict[str, Any]
    noise_seed: int
    source_mode: SourceMode


def build_validation_matrix(
    *,
    release_id: str,
    datasets: Mapping[ValidationDomain, str],
    methods: Mapping[ValidationDomain, str],
    stages: Sequence[NoiseStage],
    operators: Mapping[ValidationDomain, Mapping[NoiseStage, str]],
    runtime: Mapping[ValidationDomain, Mapping[str, Any]],
    source_modes: Mapping[ValidationDomain, SourceMode],
    provider: ValidationProvider,
    noise_seed: int,
    execution: ValidationExecution,
) -> ValidationMatrix:
    payload: dict[str, Any] = {
        "schema_version": "rsebench.validation-matrix.v1",
        "release_id": release_id,
        "datasets": dict(datasets),
        "methods": dict(methods),
        "stages": tuple(stages),
        "operators": {
            domain: dict(values) for domain, values in operators.items()
        },
        "runtime": {domain: dict(values) for domain, values in runtime.items()},
        "source_modes": dict(source_modes),
        "provider": provider,
        "noise_seed": noise_seed,
        "execution": execution,
    }
    provisional = ValidationMatrix.model_construct(
        **payload,
        content_hash="0" * 64,
    )
    content_hash = canonical_hash(
        provisional.model_dump(mode="json", exclude={"content_hash"})
    )
    return ValidationMatrix.model_validate({**payload, "content_hash": content_hash})


__all__ = [
    "SourceMode",
    "ValidationCell",
    "ValidationDomain",
    "ValidationExecution",
    "ValidationMatrix",
    "ValidationProvider",
    "build_validation_matrix",
]
