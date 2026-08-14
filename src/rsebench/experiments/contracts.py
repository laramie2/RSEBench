"""Immutable identities shared by experiment execution and release tooling."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, UUID4, field_validator

from rsebench.contracts import StrictModel
from rsebench.evidence import canonical_hash
from rsebench.experiments.bootstrap import BaselineFingerprint


class _FrozenStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperimentIdentityInput(_FrozenStrictModel):
    repository_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    baseline: BaselineFingerprint
    environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_hashes: dict[str, str]
    seed_skill_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    runtime: dict[str, Any]
    benchmark: str = Field(min_length=1)
    stage: Literal["clean", "N1", "N2", "N3", "N4"]
    method_seed: int

    @field_validator("dataset_hashes")
    @classmethod
    def validate_dataset_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("dataset_hashes must not be empty")
        for name, digest in value.items():
            if not name:
                raise ValueError("dataset hash names must not be empty")
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError(f"dataset hash is not lowercase SHA-256: {name}")
        return value


class ExperimentIdentity(_FrozenStrictModel):
    experiment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs: ExperimentIdentityInput


class AttemptIdentity(_FrozenStrictModel):
    experiment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_id: UUID4
    attempt_number: int = Field(ge=1)


def build_experiment_identity(
    inputs: ExperimentIdentityInput,
) -> ExperimentIdentity:
    """Build a deterministic content identity from canonical JSON inputs."""

    return ExperimentIdentity(experiment_id=canonical_hash(inputs), inputs=inputs)


def build_attempt_identity(
    identity: ExperimentIdentity,
    *,
    attempt_number: int,
    attempt_id: UUID | str | None = None,
) -> AttemptIdentity:
    """Create an opaque execution identity without changing experiment scope."""

    return AttemptIdentity(
        experiment_id=identity.experiment_id,
        attempt_id=attempt_id or uuid4(),
        attempt_number=attempt_number,
    )


__all__ = [
    "AttemptIdentity",
    "ExperimentIdentity",
    "ExperimentIdentityInput",
    "build_attempt_identity",
    "build_experiment_identity",
]
