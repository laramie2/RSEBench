import copy
import json
import operator
from collections.abc import Callable
from pathlib import Path, PosixPath
from typing import Any

import pytest
from pydantic import ValidationError

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.selection import (
    CandidateDecision,
    CandidateSeedEvidence,
    ConfirmationSeal,
    ConfirmationSplit,
    DomainSelectionStatus,
    ExposureLevel,
    ExposureRecord,
    ExposureRegistry,
    ExposureSource,
    ResourceLock,
    ResourceReference,
    ScreeningGeneralizationDecision,
    ScreeningSeedEvidence,
    SelectionReleaseManifest,
    SelectionStatus,
    StableSplitCandidate,
    selection_key,
)


HASH = "a" * 64


class _MutableMetadataValue:
    def __init__(self) -> None:
        self.values: list[str] = []


class _StatefulStr(str):
    state: list[str]


class _StatefulInt(int):
    state: list[str]


class _StatefulPath(PosixPath):
    rendered: str

    def __new__(cls, value: str) -> "_StatefulPath":
        instance = super().__new__(cls, value)
        instance.rendered = value
        return instance

    def __str__(self) -> str:
        return self.rendered


def _task(
    task_id: str,
    *,
    benchmark: str = "officeqa_full",
    domain: str = "document",
    metadata: dict[str, Any] | None = None,
) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain=domain,
        prompt=f"Question {task_id}",
        gold_answers=["answer"],
        source_hash=HASH,
        metadata=metadata or {},
    )


def _candidate(**updates: object) -> StableSplitCandidate:
    values = {
        "benchmark": "officeqa_full",
        "domain": "document",
        "candidate_index": 2,
        "train": [_task("train")],
        "validation": [_task("validation")],
        "qualification_test": [_task("qualification")],
        "screening_test": [_task("screening")],
        "source_hash": HASH,
        "selection_hash": HASH,
    }
    values.update(updates)
    return StableSplitCandidate(**values)


def test_selection_key_is_role_sensitive() -> None:
    screen = selection_key(
        benchmark="officeqa_full",
        role="screening_test",
        candidate_index=2,
        stratum="hard|files=2-3",
        task_id="UID0042",
    )
    confirm = selection_key(
        benchmark="officeqa_full",
        role="confirmation_test",
        candidate_index=2,
        stratum="hard|files=2-3",
        task_id="UID0042",
    )

    assert len(screen) == 64
    assert screen != confirm
    assert screen == canonical_hash(
        [
            "noise-screen-v1",
            "officeqa_full",
            "screening_test",
            2,
            "hard|files=2-3",
            "UID0042",
        ]
    )


def test_candidate_roles_must_be_disjoint() -> None:
    with pytest.raises(ValidationError, match="disjoint"):
        _candidate(screening_test=[_task("train")])


def test_candidate_rejects_duplicate_ids_and_mismatched_task_identity() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _candidate(train=[_task("same"), _task("same")])
    with pytest.raises(ValidationError, match="benchmark"):
        _candidate(train=[_task("other", benchmark="webshop")])
    with pytest.raises(ValidationError, match="domain"):
        _candidate(train=[_task("other", domain="spreadsheet")])


def test_candidate_is_immutable_and_strictly_bounded() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError, match="frozen"):
        candidate.candidate_index = 3
    with pytest.raises(ValidationError):
        _candidate(candidate_index=4)
    with pytest.raises(ValidationError):
        _candidate(source_hash="A" * 64)
    with pytest.raises(ValidationError):
        StableSplitCandidate(**_candidate().model_dump(), unexpected=True)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        pytest.param(
            lambda candidate: candidate.train.append(_task("appended")),
            TypeError,
            id="train-append",
        ),
        pytest.param(
            lambda candidate: operator.setitem(
                candidate.train,
                0,
                _task("replacement"),
            ),
            TypeError,
            id="train-item-assignment",
        ),
        pytest.param(
            lambda candidate: operator.setitem(candidate.metadata, "changed", True),
            TypeError,
            id="candidate-metadata",
        ),
        pytest.param(
            lambda candidate: setattr(candidate.train[0], "task_id", "changed"),
            ValidationError,
            id="nested-task-attribute",
        ),
        pytest.param(
            lambda candidate: candidate.train[0].gold_answers.append("changed"),
            TypeError,
            id="nested-task-gold-answers",
        ),
        pytest.param(
            lambda candidate: operator.setitem(
                candidate.train[0].metadata,
                "changed",
                True,
            ),
            TypeError,
            id="nested-task-metadata",
        ),
        pytest.param(
            lambda candidate: candidate.train[0].metadata["nested"]["tags"].append(
                "changed"
            ),
            TypeError,
            id="recursively-nested-task-metadata",
        ),
    ],
)
def test_candidate_rejects_deep_mutation(
    mutation: Callable[[StableSplitCandidate], object],
    expected_error: type[Exception],
) -> None:
    candidate = _candidate(
        metadata={"selection": {"version": "v1"}},
        train=[_task("train", metadata={"nested": {"tags": ["original"]}})],
    )

    with pytest.raises(expected_error, match="immutable|frozen"):
        mutation(candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda candidate: candidate.train.__init__([_task("replacement")]),
            id="sequence-reinitialization",
        ),
        pytest.param(
            lambda candidate: candidate.metadata.__init__({"changed": True}),
            id="mapping-reinitialization",
        ),
        pytest.param(
            lambda candidate: candidate.train[0].metadata["nested"]["tags"].__init__(
                ["changed"]
            ),
            id="recursive-sequence-reinitialization",
        ),
        pytest.param(
            lambda candidate: list.append(candidate.train, _task("appended")),
            id="direct-list-append",
        ),
        pytest.param(
            lambda candidate: dict.__setitem__(candidate.metadata, "changed", True),
            id="direct-dict-assignment",
        ),
        pytest.param(
            lambda candidate: list.append(
                candidate.train[0].metadata["nested"]["tags"],
                "changed",
            ),
            id="recursive-direct-list-append",
        ),
        pytest.param(
            lambda candidate: dict.__setitem__(
                candidate.train[0].metadata["nested"],
                "changed",
                True,
            ),
            id="recursive-direct-dict-assignment",
        ),
        pytest.param(
            lambda candidate: setattr(candidate.train, "_items", ()),
            id="sequence-private-state-assignment",
        ),
        pytest.param(
            lambda candidate: setattr(candidate.metadata, "_items", ()),
            id="mapping-private-state-assignment",
        ),
    ],
)
def test_candidate_rejects_mutable_builtin_bypasses(
    mutation: Callable[[StableSplitCandidate], object],
) -> None:
    candidate = _candidate(
        metadata={"selection": {"version": "v1"}},
        train=[_task("train", metadata={"nested": {"tags": ["original"]}})],
    )

    with pytest.raises(TypeError):
        mutation(candidate)


@pytest.mark.parametrize(
    "copier",
    [
        pytest.param(copy.deepcopy, id="copy-deepcopy"),
        pytest.param(
            lambda candidate: candidate.model_copy(deep=True),
            id="pydantic-model-copy-deep",
        ),
    ],
)
def test_deep_copies_succeed_and_remain_deeply_immutable(
    copier: Callable[[StableSplitCandidate], StableSplitCandidate],
) -> None:
    candidate = _candidate(
        metadata={"selection": {"version": "v1"}},
        train=[_task("train", metadata={"nested": {"tags": ["original"]}})],
    )

    copied = copier(candidate)

    assert copied is not candidate
    assert copied == candidate
    assert copied.model_dump(mode="json") == candidate.model_dump(mode="json")
    assert canonical_hash(copied) == canonical_hash(candidate)
    with pytest.raises(TypeError):
        copied.train.__init__([_task("replacement")])
    with pytest.raises(TypeError):
        copied.metadata.__init__({"changed": True})
    with pytest.raises(TypeError):
        copied.train[0].gold_answers.append("changed")
    with pytest.raises(TypeError):
        operator.setitem(copied.train[0].metadata["nested"], "changed", True)


def _registry() -> ExposureRegistry:
    return ExposureRegistry(
        records=[
            ExposureRecord(
                benchmark="officeqa_full",
                task_id="UID0042",
                level=ExposureLevel.manifest_only,
                roles=["train"],
                sources=["manifest"],
            )
        ],
        registry_hash=HASH,
    )


def _status() -> SelectionStatus:
    return SelectionStatus(
        domains={
            "document": DomainSelectionStatus(
                benchmark="officeqa_full",
                selected_candidate_index=1,
                next_action="freeze_candidate",
                reasons=["qualified"],
            )
        }
    )


def _seal() -> ConfirmationSeal:
    return ConfirmationSeal(
        created_before_screening=True,
        split_hashes={"document": HASH},
        task_ids={"document": ["confirm"]},
        exposure_registry_hash=HASH,
    )


def _release() -> SelectionReleaseManifest:
    return SelectionReleaseManifest(
        selection_version="noise-screen-v1",
        selected_candidate_indices={"document": 1},
        screening_split_hashes={"document": HASH},
        confirmation_split_hashes={"document": HASH},
        exposure_registry_hash=HASH,
        resource_lock_hash=HASH,
        baseline_fingerprints={"skillopt": HASH},
        domain_statuses={"document": "clean_generalization_ready"},
    )


@pytest.mark.parametrize(
    ("factory", "mutation"),
    [
        pytest.param(
            _registry,
            lambda registry: registry.records.append(registry.records[0]),
            id="registry-record-list",
        ),
        pytest.param(
            _registry,
            lambda registry: registry.records[0].roles.append("test"),
            id="registry-nested-role-list",
        ),
        pytest.param(
            _status,
            lambda status: operator.setitem(
                status.domains,
                "spreadsheet",
                status.domains["document"],
            ),
            id="status-domain-dict",
        ),
        pytest.param(
            _status,
            lambda status: status.domains["document"].reasons.append("changed"),
            id="status-nested-reason-list",
        ),
        pytest.param(
            _seal,
            lambda seal: seal.task_ids["document"].append("changed"),
            id="seal-nested-task-list",
        ),
        pytest.param(
            _seal,
            lambda seal: operator.setitem(seal.split_hashes, "changed", HASH),
            id="seal-hash-dict",
        ),
        pytest.param(
            _release,
            lambda release: operator.setitem(
                release.selected_candidate_indices,
                "changed",
                2,
            ),
            id="release-candidate-dict",
        ),
        pytest.param(
            _release,
            lambda release: operator.setitem(
                release.baseline_fingerprints,
                "changed",
                HASH,
            ),
            id="release-fingerprint-dict",
        ),
    ],
)
def test_selection_contracts_reject_representative_deep_mutation(
    factory: Callable[[], Any],
    mutation: Callable[[Any], object],
) -> None:
    with pytest.raises(TypeError, match="immutable"):
        mutation(factory())


def test_deep_freeze_preserves_inputs_schema_serialization_and_hashes() -> None:
    source_task = _task(
        "train",
        metadata={"nested": {"tags": ["original"]}},
    )
    input_payload = {
        "benchmark": "officeqa_full",
        "domain": "document",
        "candidate_index": 2,
        "train": [source_task.model_dump(mode="json")],
        "validation": [_task("validation").model_dump(mode="json")],
        "qualification_test": [_task("qualification").model_dump(mode="json")],
        "screening_test": [_task("screening").model_dump(mode="json")],
        "source_hash": HASH,
        "selection_hash": HASH,
        "metadata": {"selection": {"version": "v1"}},
    }

    candidate = StableSplitCandidate.model_validate(input_payload)

    assert candidate.model_dump(mode="json", warnings="error") == {
        "schema_version": "rsebench.stable-split-candidate.v1",
        **input_payload,
    }
    assert json.loads(candidate.model_dump_json(warnings="error")) == candidate.model_dump(
        mode="json"
    )
    assert canonical_hash(candidate) == canonical_hash(candidate.model_dump(mode="json"))
    for schema_mode in ("validation", "serialization"):
        schema = StableSplitCandidate.model_json_schema(mode=schema_mode)
        assert schema["properties"]["train"]["type"] == "array"
        assert schema["properties"]["metadata"]["type"] == "object"

    source_task.task_id = "source-remains-mutable"
    source_task.gold_answers.append("source-remains-mutable")
    source_task.metadata["nested"]["tags"].append("source-remains-mutable")
    assert candidate.train[0].task_id == "train"
    assert candidate.train[0].gold_answers == ["answer"]
    assert candidate.train[0].metadata == {"nested": {"tags": ["original"]}}


@pytest.mark.parametrize(
    "bad_value_factory",
    [
        pytest.param(lambda: bytearray(b"mutable"), id="bytearray"),
        pytest.param(_MutableMetadataValue, id="custom-mutable-object"),
    ],
)
@pytest.mark.parametrize("location", ["candidate", "nested-task"])
def test_candidate_rejects_noncanonical_mutable_metadata_values(
    bad_value_factory: Callable[[], object],
    location: str,
) -> None:
    bad_value = bad_value_factory()

    with pytest.raises(ValidationError, match="stable canonical values"):
        if location == "candidate":
            _candidate(metadata={"bad": bad_value})
        else:
            _candidate(train=[_task("train", metadata={"bad": bad_value})])


def test_supported_metadata_is_unaliased_and_canonical_output_remains_stable() -> None:
    candidate_metadata = {"nested": {"values": [1]}}
    task_metadata = {"nested": {"values": [2]}}
    candidate = _candidate(
        metadata=candidate_metadata,
        train=[_task("train", metadata=task_metadata)],
    )
    original_dump = candidate.model_dump(mode="json")
    original_hash = canonical_hash(candidate)

    candidate_metadata["nested"]["values"].append(3)
    task_metadata["nested"]["values"].append(4)

    assert candidate.model_dump(mode="json") == original_dump
    assert canonical_hash(candidate) == original_hash


def test_scalar_and_path_subclasses_are_normalized_without_aliases() -> None:
    candidate_text = _StatefulStr("candidate")
    candidate_text.state = []
    candidate_number = _StatefulInt(7)
    candidate_number.state = []
    candidate_path = _StatefulPath("/candidate/original")
    task_text = _StatefulStr("task")
    task_text.state = []
    task_number = _StatefulInt(11)
    task_number.state = []
    task_path = _StatefulPath("/task/original")
    candidate = _candidate(
        metadata={
            "text": candidate_text,
            "number": candidate_number,
            "path": candidate_path,
        },
        train=[
            _task(
                "train",
                metadata={
                    "text": task_text,
                    "number": task_number,
                    "path": task_path,
                },
            )
        ],
    )
    original_dump = candidate.model_dump(mode="json")
    original_hash = canonical_hash(candidate)

    assert type(candidate.metadata["text"]) is str
    assert type(candidate.metadata["number"]) is int
    assert type(candidate.metadata["path"]) is type(Path())
    assert candidate.metadata["text"] is not candidate_text
    assert candidate.metadata["number"] is not candidate_number
    assert candidate.metadata["path"] is not candidate_path
    assert type(candidate.train[0].metadata["text"]) is str
    assert type(candidate.train[0].metadata["number"]) is int
    assert type(candidate.train[0].metadata["path"]) is type(Path())
    assert candidate.train[0].metadata["text"] is not task_text
    assert candidate.train[0].metadata["number"] is not task_number
    assert candidate.train[0].metadata["path"] is not task_path
    candidate_text.state.append("changed")
    candidate_number.state.append("changed")
    candidate_path.rendered = "/candidate/changed"
    task_text.state.append("changed")
    task_number.state.append("changed")
    task_path.rendered = "/task/changed"

    assert candidate.model_dump(mode="json") == original_dump
    assert canonical_hash(candidate) == original_hash


def test_exposure_source_normalizes_path_subclass_and_preserves_typed_enum() -> None:
    source_path = _StatefulPath("/source/original")
    source = ExposureSource(
        label="history",
        root=source_path,
        level=ExposureLevel.executed,
    )
    original_dump = source.model_dump(mode="json")
    original_hash = canonical_hash(source)

    assert type(source.root) is type(Path())
    assert source.root is not source_path
    assert source.level is ExposureLevel.executed
    source_path.rendered = "/source/changed"

    assert str(source.root) == "/source/original"
    assert source.model_dump(mode="json") == original_dump
    assert canonical_hash(source) == original_hash


def test_finite_float_metadata_remains_supported() -> None:
    candidate = _candidate(metadata={"ratio": 0.125})

    assert type(candidate.metadata["ratio"]) is float
    assert candidate.model_dump(mode="json")["metadata"]["ratio"] == 0.125


def test_nested_model_dump_honors_exclude_none() -> None:
    candidate = _candidate()

    dumped = candidate.model_dump(exclude_none=True)

    assert "artifact_path" not in dumped["train"][0]
    assert "verifier" not in dumped["train"][0]


def test_nested_model_dump_honors_include_and_exclude() -> None:
    candidate = _candidate(
        train=[_task("train", metadata={"keep": True, "drop": False})],
    )

    included = candidate.model_dump(
        include={"train": {0: {"task_id", "metadata"}}},
    )
    excluded = candidate.model_dump(
        exclude={"train": {0: {"prompt", "metadata"}}},
    )

    assert included == {
        "train": [{"task_id": "train", "metadata": {"keep": True, "drop": False}}]
    }
    assert excluded["train"][0]["task_id"] == "train"
    assert "prompt" not in excluded["train"][0]
    assert "metadata" not in excluded["train"][0]


def test_confirmation_roles_must_be_disjoint_and_match_identity() -> None:
    with pytest.raises(ValidationError, match="disjoint"):
        ConfirmationSplit(
            benchmark="officeqa_full",
            domain="document",
            train=[_task("train")],
            validation=[_task("validation")],
            confirmation_test=[_task("train")],
            source_hash=HASH,
            selection_hash=HASH,
        )


def test_decision_and_release_contracts_use_exact_literals_and_ranges() -> None:
    candidate_evidence = CandidateSeedEvidence(
        method_seed=1,
        accepted_update_count=1,
        artifact_changed=True,
        mean_delta_vs_seed=0.2,
        execution_complete=True,
        replay_count=3,
    )
    screening_evidence = ScreeningSeedEvidence(
        method_seed=1,
        mean_delta_vs_seed=0.1,
        execution_complete=True,
        replay_count=3,
    )
    generalization = ScreeningGeneralizationDecision(
        status="clean_generalization_ready",
        nondegrading_seed_count=3,
        mean_clean_gain=0.1,
        execution_coverage=1.0,
        failure_reasons=[],
    )
    decision = CandidateDecision(
        candidate_index=1,
        passed=True,
        accepted_seed_count=2,
        nondegrading_seed_count=3,
        mean_clean_gain=0.1,
        execution_coverage=1.0,
        noise_applicability=1.0,
        next_action="freeze_candidate",
        failure_reasons=[],
    )
    status = SelectionStatus(
        domains={
            "document": DomainSelectionStatus(
                benchmark="officeqa_full",
                selected_candidate_index=1,
                next_action="freeze_candidate",
            )
        }
    )
    seal = ConfirmationSeal(
        created_before_screening=True,
        split_hashes={"document": HASH},
        task_ids={"document": ["confirm"]},
        exposure_registry_hash=HASH,
    )
    lock = ResourceLock(
        resources=[
            ResourceReference(
                uri="https://example.invalid/repo.git",
                kind="git",
                sha256=HASH,
                materialization="git clone",
            )
        ]
    )
    release = SelectionReleaseManifest(
        selection_version="noise-screen-v1",
        selected_candidate_indices={"document": 1},
        screening_split_hashes={"document": HASH},
        confirmation_split_hashes={"document": HASH},
        exposure_registry_hash=HASH,
        resource_lock_hash=HASH,
        baseline_fingerprints={"skillopt": HASH},
        domain_statuses={"document": "clean_generalization_ready"},
    )

    assert candidate_evidence.replay_count == screening_evidence.replay_count == 3
    assert generalization.status == "clean_generalization_ready"
    assert decision.next_action == "freeze_candidate"
    assert status.domains["document"].benchmark == "officeqa_full"
    assert seal.split_hashes == {"document": HASH}
    assert lock.resources[0].kind == "git"
    assert release.selection_version == "noise-screen-v1"

    with pytest.raises(ValidationError):
        CandidateSeedEvidence(
            **{**candidate_evidence.model_dump(), "replay_count": 2}
        )
    with pytest.raises(ValidationError):
        SelectionReleaseManifest(
            **{
                **release.model_dump(),
                "selected_candidate_indices": {"document": 4},
            }
        )
    with pytest.raises(ValidationError):
        ConfirmationSeal(
            **{
                **seal.model_dump(),
                "split_hashes": {"document": "not-a-hash"},
            }
        )
