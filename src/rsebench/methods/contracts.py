"""Immutable identities for validated self-evolution method releases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from rsebench.datasets import EvidenceReference
from rsebench.datasets.contracts import FrozenStrictModel
from rsebench.evidence import canonical_hash


_HASH_PATTERN = r"^[0-9a-f]{64}$"
_REVISION_PATTERN = r"^[0-9a-f]{40}$"


class PatchIdentity(FrozenStrictModel):
    """One ordered, content-addressed integration patch."""

    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=_HASH_PATTERN)
    purpose: Literal["provider", "evidence", "compatibility", "robustness"]


class HarnessIdentity(FrozenStrictModel):
    """The method-owned entrypoint and behavior identity."""

    entrypoint: str = Field(min_length=1)
    version: str = Field(min_length=1)
    fingerprint: str = Field(pattern=_HASH_PATTERN)


class ProviderIdentity(FrozenStrictModel):
    """Provider-facing runtime profile without credentials."""

    family: str = Field(min_length=1)
    model: str = Field(min_length=1)
    adapter: str = Field(min_length=1)


class MethodRelease(FrozenStrictModel):
    """A reproducible validated method plus its clean control identity."""

    schema_version: Literal["rsebench.method-release.v1"] = (
        "rsebench.method-release.v1"
    )
    release_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    status: Literal["active", "validated_inactive"]
    upstream_repository: str = Field(min_length=1)
    upstream_revision: str = Field(pattern=_REVISION_PATTERN)
    patch_series: tuple[PatchIdentity, ...] = Field(min_length=1)
    harness: HarnessIdentity
    provider: ProviderIdentity
    environment_lock: str = Field(min_length=1)
    supported_datasets: tuple[str, ...] = Field(min_length=1)
    clean_evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    smoke_command: tuple[str, ...] = Field(min_length=1)
    baseline_fingerprint: str = Field(pattern=_HASH_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = Field(pattern=_HASH_PATTERN)

    @field_validator(
        "patch_series",
        "supported_datasets",
        "clean_evidence",
        "smoke_command",
        mode="before",
    )
    @classmethod
    def normalize_sequences(cls, value: Sequence[Any]) -> tuple[Any, ...]:
        return tuple(value)

    @field_validator("upstream_repository")
    @classmethod
    def require_https_upstream(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("upstream repository must use HTTPS")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> "MethodRelease":
        if len(set(self.supported_datasets)) != len(self.supported_datasets):
            raise ValueError("duplicate supported dataset identity")
        patch_uris = tuple(patch.uri for patch in self.patch_series)
        if len(set(patch_uris)) != len(patch_uris):
            raise ValueError("duplicate patch identity")
        if any(not part for part in self.smoke_command):
            raise ValueError("smoke command contains an empty argument")
        expected = canonical_hash(
            self.model_dump(mode="json", exclude={"content_hash"})
        )
        if self.content_hash != expected:
            raise ValueError(
                f"method release content hash differs: {self.content_hash} != {expected}"
            )
        return self


def build_method_release(
    *,
    release_id: str,
    method: str,
    status: Literal["active", "validated_inactive"],
    upstream_repository: str,
    upstream_revision: str,
    patch_series: Sequence[PatchIdentity],
    harness: HarnessIdentity,
    provider: ProviderIdentity,
    environment_lock: str,
    supported_datasets: Sequence[str],
    clean_evidence: Sequence[EvidenceReference],
    smoke_command: Sequence[str],
    baseline_fingerprint: str,
    metadata: Mapping[str, Any] | None = None,
) -> MethodRelease:
    """Build a release with a canonical hash over every identity field."""

    payload: dict[str, Any] = {
        "schema_version": "rsebench.method-release.v1",
        "release_id": release_id,
        "method": method,
        "status": status,
        "upstream_repository": upstream_repository,
        "upstream_revision": upstream_revision,
        "patch_series": tuple(patch_series),
        "harness": harness,
        "provider": provider,
        "environment_lock": environment_lock,
        "supported_datasets": tuple(supported_datasets),
        "clean_evidence": tuple(clean_evidence),
        "smoke_command": tuple(smoke_command),
        "baseline_fingerprint": baseline_fingerprint,
        "metadata": dict(metadata or {}),
    }
    provisional = MethodRelease.model_construct(
        **payload,
        content_hash="0" * 64,
    )
    content_hash = canonical_hash(
        provisional.model_dump(mode="json", exclude={"content_hash"})
    )
    return MethodRelease.model_validate({**payload, "content_hash": content_hash})


__all__ = [
    "HarnessIdentity",
    "MethodRelease",
    "PatchIdentity",
    "ProviderIdentity",
    "build_method_release",
]
