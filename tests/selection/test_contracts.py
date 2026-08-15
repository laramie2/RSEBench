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


def _task(
    task_id: str,
    *,
    benchmark: str = "officeqa_full",
    domain: str = "document",
) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain=domain,
        prompt=f"Question {task_id}",
        gold_answers=["answer"],
        source_hash=HASH,
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
