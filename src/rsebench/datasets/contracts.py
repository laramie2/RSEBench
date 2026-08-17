"""Immutable identities for benchmark dataset releases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evidence import canonical_hash


_HASH_PATTERN = r"^[0-9a-f]{64}$"


class FrozenStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceIdentity(FrozenStrictModel):
    """One portable immutable resource referenced by a dataset release."""

    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=_HASH_PATTERN)
    kind: str = Field(default="artifact", min_length=1)


class EvidenceReference(FrozenStrictModel):
    """A content-addressed provenance record supporting a release decision."""

    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=_HASH_PATTERN)
    kind: str = Field(default="manifest", min_length=1)


class DatasetRelease(FrozenStrictModel):
    """A path-independent frozen benchmark task collection."""

    schema_version: Literal["rsebench.dataset-release.v1"] = (
        "rsebench.dataset-release.v1"
    )
    release_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    loader: str = Field(min_length=1)
    verifier: str = Field(min_length=1)
    tasks: dict[str, TaskManifest] = Field(min_length=1)
    partitions: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    groups: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    source_resources: tuple[ResourceIdentity, ...] = ()
    provenance: tuple[EvidenceReference, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = Field(pattern=_HASH_PATTERN)

    @field_validator("partitions", "groups", mode="before")
    @classmethod
    def normalize_memberships(
        cls, value: Mapping[str, Sequence[str]] | None
    ) -> dict[str, tuple[str, ...]]:
        if value is None:
            return {}
        return {str(name): tuple(members) for name, members in value.items()}

    @model_validator(mode="after")
    def validate_identity(self) -> "DatasetRelease":
        if any(not name for name in self.tasks):
            raise ValueError("task mapping keys must not be empty")
        for key, task in self.tasks.items():
            if key != task.task_id:
                raise ValueError(
                    f"task mapping key differs from task identity: {key} != {task.task_id}"
                )
            if task.benchmark != self.benchmark:
                raise ValueError(f"task benchmark differs for {key}")
            if task.domain != self.domain:
                raise ValueError(f"task domain differs for {key}")
        known = set(self.tasks)
        for collection_name, collection in (
            ("partition", self.partitions),
            ("group", self.groups),
        ):
            for name, members in collection.items():
                if not name:
                    raise ValueError(f"{collection_name} names must not be empty")
                seen: set[str] = set()
                for task_id in members:
                    if task_id not in known:
                        raise ValueError(
                            f"{collection_name} {name} contains unknown task: {task_id}"
                        )
                    if task_id in seen:
                        raise ValueError(
                            f"{collection_name} {name} contains duplicate task: {task_id}"
                        )
                    seen.add(task_id)
        expected = canonical_hash(
            self.model_dump(mode="json", exclude={"content_hash"})
        )
        if self.content_hash != expected:
            raise ValueError(
                f"dataset release content hash differs: {self.content_hash} != {expected}"
            )
        return self


def build_dataset_release(
    *,
    release_id: str,
    domain: str,
    benchmark: str,
    benchmark_version: str,
    loader: str,
    verifier: str,
    tasks: Mapping[str, TaskManifest],
    partitions: Mapping[str, Sequence[str]] | None = None,
    groups: Mapping[str, Sequence[str]] | None = None,
    source_resources: Sequence[ResourceIdentity] = (),
    provenance: Sequence[EvidenceReference] = (),
    metadata: Mapping[str, Any] | None = None,
) -> DatasetRelease:
    """Build a release whose content hash covers every path-independent field."""

    payload: dict[str, Any] = {
        "schema_version": "rsebench.dataset-release.v1",
        "release_id": release_id,
        "domain": domain,
        "benchmark": benchmark,
        "benchmark_version": benchmark_version,
        "loader": loader,
        "verifier": verifier,
        "tasks": dict(tasks),
        "partitions": {
            str(name): tuple(members) for name, members in (partitions or {}).items()
        },
        "groups": {
            str(name): tuple(members) for name, members in (groups or {}).items()
        },
        "source_resources": tuple(source_resources),
        "provenance": tuple(provenance),
        "metadata": dict(metadata or {}),
    }
    # Serialize through the release model before hashing so nested Pydantic
    # models and tuples use exactly the same JSON representation that the
    # validator checks when the release is loaded again.
    provisional = DatasetRelease.model_construct(
        **payload,
        content_hash="0" * 64,
    )
    content_hash = canonical_hash(
        provisional.model_dump(mode="json", exclude={"content_hash"})
    )
    return DatasetRelease.model_validate({**payload, "content_hash": content_hash})


__all__ = [
    "DatasetRelease",
    "EvidenceReference",
    "FrozenStrictModel",
    "ResourceIdentity",
    "build_dataset_release",
]
