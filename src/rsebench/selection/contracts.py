"""Typed contracts for deterministic benchmark sample selection."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evidence import canonical_hash


_HASH_PATTERN = r"^[0-9a-f]{64}$"


def _immutable_collection(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise TypeError("selection contract collections are immutable")


class _ImmutableSequence(Sequence[Any]):
    __slots__ = ("_items",)

    def __init__(self, values: Iterable[Any]) -> None:
        if hasattr(self, "_items"):
            _immutable_collection()
        object.__setattr__(self, "_items", tuple(values))

    def __getitem__(self, index: int | slice) -> Any:
        return self._items[index]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sequence) and not isinstance(
            other,
            (str, bytes, bytearray),
        ):
            return self._items == tuple(other)
        return False

    def __add__(self, other: Sequence[Any]) -> list[Any]:
        return [*self, *other]

    def __radd__(self, other: Sequence[Any]) -> list[Any]:
        return [*other, *self]

    def __copy__(self) -> "_ImmutableSequence":
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> "_ImmutableSequence":
        memo[id(self)] = self
        return self

    def __repr__(self) -> str:
        return repr(self._items)

    __setattr__ = _immutable_collection
    __delattr__ = _immutable_collection
    __setitem__ = _immutable_collection
    __delitem__ = _immutable_collection
    __iadd__ = _immutable_collection
    __imul__ = _immutable_collection
    append = _immutable_collection
    clear = _immutable_collection
    extend = _immutable_collection
    insert = _immutable_collection
    pop = _immutable_collection
    remove = _immutable_collection
    reverse = _immutable_collection
    sort = _immutable_collection


class _ImmutableMapping(Mapping[Any, Any]):
    __slots__ = ("_items",)

    def __init__(
        self,
        values: Mapping[Any, Any] | Iterable[tuple[Any, Any]],
    ) -> None:
        if hasattr(self, "_items"):
            _immutable_collection()
        items = values.items() if isinstance(values, Mapping) else values
        object.__setattr__(self, "_items", tuple(items))

    def __getitem__(self, key: Any) -> Any:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[Any]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return False
        return dict(self.items()) == dict(other.items())

    def __copy__(self) -> "_ImmutableMapping":
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> "_ImmutableMapping":
        memo[id(self)] = self
        return self

    def __repr__(self) -> str:
        return repr(dict(self._items))

    def copy(self) -> dict[Any, Any]:
        return dict(self._items)

    __setattr__ = _immutable_collection
    __delattr__ = _immutable_collection
    __setitem__ = _immutable_collection
    __delitem__ = _immutable_collection
    __ior__ = _immutable_collection
    clear = _immutable_collection
    pop = _immutable_collection
    popitem = _immutable_collection
    setdefault = _immutable_collection
    update = _immutable_collection


def _deep_freeze(value: Any) -> Any:
    if isinstance(
        value,
        (
            _ImmutableSequence,
            _ImmutableMapping,
            _ImmutableSelectionModel,
        ),
    ):
        return value
    if isinstance(value, TaskManifest):
        immutable = _ImmutableTaskManifest.model_validate(
            value.model_dump(mode="python")
        )
        object.__setattr__(
            immutable,
            "__pydantic_fields_set__",
            set(value.model_fields_set),
        )
        return immutable
    if isinstance(value, dict):
        normalized_items: list[tuple[str, Any]] = []
        normalized_keys: set[str] = set()
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    "selection contracts require stable canonical values; "
                    "mapping keys must be strings"
                )
            normalized_key = str(key)
            if normalized_key in normalized_keys:
                raise ValueError(
                    "selection contracts require stable canonical values; "
                    f"duplicate normalized mapping key: {normalized_key!r}"
                )
            normalized_keys.add(normalized_key)
            normalized_items.append((normalized_key, _deep_freeze(child)))
        return _ImmutableMapping(normalized_items)
    if isinstance(value, (list, tuple)):
        return _ImmutableSequence(_deep_freeze(child) for child in value)
    if isinstance(value, ExposureLevel):
        return ExposureLevel(value.value)
    if isinstance(value, Enum):
        return _deep_freeze(value.value)
    if isinstance(value, Path):
        return Path(str(value))
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and math.isfinite(normalized := float(value)):
        return normalized
    raise ValueError(
        "selection contracts require stable canonical values; "
        f"unsupported type: {type(value).__name__}"
    )


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, _ImmutableTaskManifest):
        return TaskManifest.model_construct(
            _fields_set=set(value.model_fields_set),
            **{
                field_name: _deep_thaw(field_value)
                for field_name, field_value in value.__dict__.items()
            },
        )
    if isinstance(value, _ImmutableSequence):
        return [_deep_thaw(child) for child in value]
    if isinstance(value, _ImmutableMapping):
        return {key: _deep_thaw(child) for key, child in value.items()}
    return value


class _ImmutableSelectionModel(StrictModel):
    model_config = ConfigDict(frozen=True)

    def model_post_init(self, context: Any, /) -> None:
        del context
        for field_name, value in self.__dict__.items():
            object.__setattr__(self, field_name, _deep_freeze(value))

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)

        fields_set = self.model_fields_set | set(update)
        payload = self.model_dump(mode="python")
        payload.update(update)
        copied = type(self).model_validate(payload)
        object.__setattr__(copied, "__pydantic_fields_set__", fields_set)
        return copied

    @field_serializer("*", mode="wrap", check_fields=False)
    def serialize_immutable_field(
        self,
        value: Any,
        serializer: Any,
    ):
        return serializer(_deep_thaw(value))


class _ImmutableTaskManifest(TaskManifest):
    model_config = ConfigDict(frozen=True)

    def model_post_init(self, context: Any, /) -> None:
        del context
        for field_name, value in self.__dict__.items():
            object.__setattr__(self, field_name, _deep_freeze(value))

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)

        fields_set = self.model_fields_set | set(update)
        payload = self.model_dump(mode="python")
        payload.update(update)
        copied = type(self).model_validate(payload)
        object.__setattr__(copied, "__pydantic_fields_set__", fields_set)
        return copied

    @field_serializer("*", mode="wrap", check_fields=False)
    def serialize_immutable_field(
        self,
        value: Any,
        serializer: Any,
    ):
        return serializer(_deep_thaw(value))


class ExposureLevel(str, Enum):
    manifest_only = "manifest_only"
    executed = "executed"
    score_observed = "score_observed"

    @property
    def rank(self) -> int:
        return {
            ExposureLevel.manifest_only: 0,
            ExposureLevel.executed: 1,
            ExposureLevel.score_observed: 2,
        }[self]


class ExposureSource(_ImmutableSelectionModel):
    label: str
    root: Path
    level: ExposureLevel
    experiment_id: str | None = None


class ExposureRecord(_ImmutableSelectionModel):
    benchmark: str
    task_id: str
    source_partition: str | None = None
    level: ExposureLevel
    roles: list[str]
    sources: list[str]
    first_experiment_id: str | None = None
    last_experiment_id: str | None = None

    @model_validator(mode="after")
    def validate_labels(self) -> "ExposureRecord":
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("exposure roles must be unique")
        if len(self.sources) != len(set(self.sources)):
            raise ValueError("exposure sources must be unique")
        return self


class ExposureRegistry(_ImmutableSelectionModel):
    schema_version: str = "rsebench.exposure-registry.v1"
    records: list[ExposureRecord]
    registry_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_unique_records(self) -> "ExposureRegistry":
        identities = [(record.benchmark, record.task_id) for record in self.records]
        if len(identities) != len(set(identities)):
            raise ValueError("exposure record IDs must be unique within each benchmark")
        return self


def _validate_task_roles(
    *,
    benchmark: str,
    domain: str,
    roles: dict[str, list[TaskManifest]],
) -> None:
    role_ids: dict[str, set[str]] = {}
    for role, tasks in roles.items():
        task_ids = [task.task_id for task in tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError(f"{role} task IDs must be unique")
        for task in tasks:
            if task.benchmark != benchmark:
                raise ValueError(
                    f"{role} task {task.task_id} benchmark must match {benchmark}"
                )
            if task.domain != domain:
                raise ValueError(
                    f"{role} task {task.task_id} domain must match {domain}"
                )
        role_ids[role] = set(task_ids)

    role_names = list(role_ids)
    for index, left in enumerate(role_names):
        for right in role_names[index + 1 :]:
            overlap = role_ids[left] & role_ids[right]
            if overlap:
                raise ValueError(
                    f"candidate roles must be disjoint; {left} and {right} overlap: "
                    f"{sorted(overlap)}"
                )


class StableSplitCandidate(_ImmutableSelectionModel):
    schema_version: str = "rsebench.stable-split-candidate.v1"
    benchmark: str
    domain: str
    candidate_index: int = Field(ge=1, le=3)
    train: list[TaskManifest]
    validation: list[TaskManifest]
    qualification_test: list[TaskManifest]
    screening_test: list[TaskManifest]
    source_hash: str = Field(pattern=_HASH_PATTERN)
    selection_hash: str = Field(pattern=_HASH_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tasks(self) -> "StableSplitCandidate":
        _validate_task_roles(
            benchmark=self.benchmark,
            domain=self.domain,
            roles={
                "train": self.train,
                "validation": self.validation,
                "qualification_test": self.qualification_test,
                "screening_test": self.screening_test,
            },
        )
        return self


class ConfirmationSplit(_ImmutableSelectionModel):
    schema_version: str = "rsebench.confirmation-split.v1"
    benchmark: str
    domain: str
    train: list[TaskManifest]
    validation: list[TaskManifest]
    confirmation_test: list[TaskManifest]
    source_hash: str = Field(pattern=_HASH_PATTERN)
    selection_hash: str = Field(pattern=_HASH_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tasks(self) -> "ConfirmationSplit":
        _validate_task_roles(
            benchmark=self.benchmark,
            domain=self.domain,
            roles={
                "train": self.train,
                "validation": self.validation,
                "confirmation_test": self.confirmation_test,
            },
        )
        return self


class CandidateSeedEvidence(_ImmutableSelectionModel):
    method_seed: int
    accepted_update_count: int = Field(ge=0)
    artifact_changed: bool
    mean_delta_vs_seed: float
    execution_complete: bool
    replay_count: int = Field(ge=3)


class ScreeningSeedEvidence(_ImmutableSelectionModel):
    method_seed: int
    mean_delta_vs_seed: float
    execution_complete: bool
    replay_count: int = Field(ge=3)


class ScreeningGeneralizationDecision(_ImmutableSelectionModel):
    status: Literal["clean_generalization_ready", "clean_generalization_failed"]
    nondegrading_seed_count: int = Field(ge=0, le=3)
    mean_clean_gain: float
    execution_coverage: float = Field(ge=0.0, le=1.0)
    failure_reasons: list[str]


class CandidateDecision(_ImmutableSelectionModel):
    schema_version: str = "rsebench.candidate-decision.v1"
    candidate_index: int = Field(ge=1, le=3)
    passed: bool
    accepted_seed_count: int = Field(ge=0, le=3)
    nondegrading_seed_count: int = Field(ge=0, le=3)
    mean_clean_gain: float
    execution_coverage: float = Field(ge=0.0, le=1.0)
    noise_applicability: float = Field(ge=0.0, le=1.0)
    next_action: Literal[
        "freeze_candidate",
        "run_candidate_2",
        "run_candidate_3",
        "extend_replay_to_5",
        "clean_blocked_after_three_candidates",
    ]
    failure_reasons: list[str]


class PoolCandidateDecision(_ImmutableSelectionModel):
    """Domain-bound CandidateDecision for one of the three pool benchmarks."""

    decision_type: Literal["pool_candidate"] = "pool_candidate"
    benchmark: Literal[
        "spreadsheetbench_verified",
        "officeqa_full",
        "webshop",
    ]
    decision: CandidateDecision


class SkillLearnFamilyQualificationSummary(_ImmutableSelectionModel):
    """Owned, hash-bound clean qualification summary for one fixed family."""

    family: str
    ready: bool
    accepted_method_seeds: list[int]
    validation_complete_method_seeds: list[int]
    execution_coverage: float = Field(ge=0.0, le=1.0)
    noise_applicability: float = Field(ge=0.0, le=1.0)
    evidence_hash: str = Field(pattern=_HASH_PATTERN)
    failure_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_seed_sets(self) -> "SkillLearnFamilyQualificationSummary":
        formal = {20260813, 20260814, 20260815}
        for field_name in (
            "accepted_method_seeds",
            "validation_complete_method_seeds",
        ):
            seeds = list(getattr(self, field_name))
            if len(seeds) != len(set(seeds)) or not set(seeds) <= formal:
                raise ValueError(f"{field_name} must be unique formal method seeds")
        expected_ready = (
            len(self.accepted_method_seeds) >= 2
            and len(self.validation_complete_method_seeds) == 3
            and self.execution_coverage == 1.0
            and self.noise_applicability == 1.0
            and not self.failure_reasons
        )
        if self.ready != expected_ready:
            raise ValueError("SkillLearn family ready flag differs from qualification")
        return self


class SkillLearnQualificationDecision(_ImmutableSelectionModel):
    """The fixed-family SkillLearn gate; deliberately not CandidateDecision."""

    decision_type: Literal["skilllearn_fixed_families"] = (
        "skilllearn_fixed_families"
    )
    benchmark: Literal["skilllearnbench"] = "skilllearnbench"
    candidate_index: Literal[1]
    required_ready_family_count: Literal[3] = 3
    evaluated_family_count: Literal[4] = 4
    ready_families: list[str]
    family_summaries: dict[str, SkillLearnFamilyQualificationSummary]
    execution_coverage: float = Field(ge=0.0, le=1.0)
    noise_applicability: float = Field(ge=0.0, le=1.0)
    passed: bool
    next_action: Literal[
        "freeze_candidate",
        "clean_blocked_skilllearn_families",
    ]
    failure_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_family_gate(self) -> "SkillLearnQualificationDecision":
        expected_families = {
            "organize-messy-files",
            "offer-letter-generator",
            "schedule-planning",
            "dependency-vulnerability-check",
        }
        if set(self.family_summaries) != expected_families:
            raise ValueError("SkillLearn decision requires exactly four fixed families")
        for family, summary in self.family_summaries.items():
            if summary.family != family:
                raise ValueError("SkillLearn summary key differs from family")
        expected_ready = sorted(
            family for family, summary in self.family_summaries.items() if summary.ready
        )
        if sorted(self.ready_families) != expected_ready or len(
            self.ready_families
        ) != len(set(self.ready_families)):
            raise ValueError("SkillLearn ready families differ from family summaries")
        expected_passed = (
            len(expected_ready) >= 3
            and self.execution_coverage == 1.0
            and self.noise_applicability == 1.0
        )
        if self.passed != expected_passed:
            raise ValueError("SkillLearn passed flag differs from fixed-family gate")
        expected_action = (
            "freeze_candidate"
            if expected_passed
            else "clean_blocked_skilllearn_families"
        )
        if self.next_action != expected_action:
            raise ValueError("SkillLearn next action differs from fixed-family gate")
        return self


SelectionAction = Literal[
    "replay_candidate_1",
    "rerun_candidate_1",
    "run_candidate_2",
    "run_candidate_3",
    "extend_replay_to_5",
    "freeze_candidate",
    "clean_blocked_after_three_candidates",
    "clean_blocked_skilllearn_families",
]


class DomainSelectionStatus(_ImmutableSelectionModel):
    benchmark: str
    selected_candidate_index: int | None = Field(default=None, ge=1, le=3)
    next_action: SelectionAction
    reasons: list[str] = Field(default_factory=list)


class SelectionStatus(_ImmutableSelectionModel):
    schema_version: str = "rsebench.selection-status.v1"
    domains: dict[str, DomainSelectionStatus]

    @model_validator(mode="after")
    def validate_domain_keys(self) -> "SelectionStatus":
        for domain_key, row in self.domains.items():
            if domain_key != row.benchmark:
                raise ValueError(
                    "selection status domain key must equal row benchmark: "
                    f"{domain_key} != {row.benchmark}"
                )
        return self


def _validate_hash_mapping(values: dict[str, str], field_name: str) -> None:
    for key, value in values.items():
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"{field_name}[{key!r}] must be a lowercase SHA-256 hash")


class ConfirmationSeal(_ImmutableSelectionModel):
    schema_version: str = "rsebench.confirmation-seal.v1"
    created_before_screening: bool
    split_hashes: dict[str, str]
    task_ids: dict[str, list[str]]
    exposure_registry_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_maps(self) -> "ConfirmationSeal":
        _validate_hash_mapping(self.split_hashes, "split_hashes")
        all_task_ids: set[str] = set()
        for role, task_ids in self.task_ids.items():
            if len(task_ids) != len(set(task_ids)):
                raise ValueError(f"task_ids[{role!r}] must contain unique IDs")
            overlap = all_task_ids & set(task_ids)
            if overlap:
                raise ValueError(
                    f"confirmation task ID roles must be disjoint: {sorted(overlap)}"
                )
            all_task_ids.update(task_ids)
        return self


class ResourceReference(_ImmutableSelectionModel):
    uri: str
    kind: Literal["git", "rsebench-data", "rsebench-methods", "external-image"]
    sha256: str = Field(pattern=_HASH_PATTERN)
    materialization: str


class ResourceLock(_ImmutableSelectionModel):
    schema_version: str = "rsebench.resource-lock.v1"
    resources: list[ResourceReference]


class SelectionReleaseManifest(_ImmutableSelectionModel):
    schema_version: str = "rsebench.selection-release.v1"
    selection_version: Literal["noise-screen-v1"]
    selected_candidate_indices: dict[str, int]
    screening_split_hashes: dict[str, str]
    confirmation_split_hashes: dict[str, str]
    exposure_registry_hash: str = Field(pattern=_HASH_PATTERN)
    resource_lock_hash: str = Field(pattern=_HASH_PATTERN)
    baseline_fingerprints: dict[str, str]
    domain_statuses: dict[str, Literal["clean_generalization_ready"]]

    @model_validator(mode="after")
    def validate_maps(self) -> "SelectionReleaseManifest":
        for domain, candidate_index in self.selected_candidate_indices.items():
            if not 1 <= candidate_index <= 3:
                raise ValueError(
                    f"selected_candidate_indices[{domain!r}] must be between 1 and 3"
                )
        _validate_hash_mapping(self.screening_split_hashes, "screening_split_hashes")
        _validate_hash_mapping(
            self.confirmation_split_hashes,
            "confirmation_split_hashes",
        )
        _validate_hash_mapping(self.baseline_fingerprints, "baseline_fingerprints")
        return self


def selection_key(
    *,
    benchmark: str,
    role: str,
    candidate_index: int,
    stratum: str,
    task_id: str,
) -> str:
    return canonical_hash(
        [
            "noise-screen-v1",
            benchmark,
            role,
            candidate_index,
            stratum,
            task_id,
        ]
    )


__all__ = [
    "CandidateDecision",
    "CandidateSeedEvidence",
    "ConfirmationSeal",
    "ConfirmationSplit",
    "DomainSelectionStatus",
    "ExposureLevel",
    "ExposureRecord",
    "ExposureRegistry",
    "ExposureSource",
    "PoolCandidateDecision",
    "ResourceLock",
    "ResourceReference",
    "ScreeningGeneralizationDecision",
    "ScreeningSeedEvidence",
    "SelectionAction",
    "SelectionReleaseManifest",
    "SelectionStatus",
    "SkillLearnFamilyQualificationSummary",
    "SkillLearnQualificationDecision",
    "StableSplitCandidate",
    "selection_key",
]
