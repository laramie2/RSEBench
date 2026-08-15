from __future__ import annotations

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.selection.contracts import (
    CandidateSeedEvidence,
    ScreeningSeedEvidence,
    StableSplitCandidate,
)
from rsebench.selection.qualification import (
    audit_officeqa,
    audit_skilllearn,
    audit_spreadsheet,
    audit_webshop,
    decide_candidate,
    decide_screening_generalization,
    replay_action,
    replay_integrity_failures,
    reuse_action,
    sequential_incomplete_action,
)
from rsebench.selection.qualification_io import (
    CleanRunEvidence,
    _group_failures,
    validate_candidate_denominators,
)


def seed_evidence(
    method_seed: int,
    *,
    accepted: int,
    changed: bool,
    mean_delta: float,
) -> CandidateSeedEvidence:
    return CandidateSeedEvidence(
        method_seed=method_seed,
        accepted_update_count=accepted,
        artifact_changed=changed,
        mean_delta_vs_seed=mean_delta,
        execution_complete=True,
        replay_count=3,
    )


def test_two_updates_two_nondegrading_and_positive_mean_pass() -> None:
    decision = decide_candidate(
        candidate_index=2,
        seeds=[
            seed_evidence(20260813, accepted=1, changed=True, mean_delta=0.08),
            seed_evidence(20260814, accepted=1, changed=True, mean_delta=0.03),
            seed_evidence(20260815, accepted=0, changed=False, mean_delta=0.00),
        ],
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    assert decision.passed is True
    assert decision.next_action == "freeze_candidate"


def test_failed_candidate_two_requests_candidate_three() -> None:
    decision = decide_candidate(
        candidate_index=2,
        seeds=[
            seed_evidence(20260813, accepted=0, changed=False, mean_delta=0.0),
            seed_evidence(20260814, accepted=1, changed=True, mean_delta=0.1),
            seed_evidence(20260815, accepted=0, changed=False, mean_delta=0.0),
        ],
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    assert decision.passed is False
    assert decision.next_action == "run_candidate_3"


def test_failed_candidate_three_fails_closed() -> None:
    decision = decide_candidate(
        candidate_index=3,
        seeds=[
            seed_evidence(seed, accepted=0, changed=False, mean_delta=0.0)
            for seed in (20260813, 20260814, 20260815)
        ],
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    assert decision.passed is False
    assert decision.next_action == "clean_blocked_after_three_candidates"


def test_candidate_requires_exact_three_unique_seeds() -> None:
    repeated = seed_evidence(20260813, accepted=1, changed=True, mean_delta=0.1)
    with pytest.raises(ValueError, match="exactly three unique seeds"):
        decide_candidate(
            candidate_index=1,
            seeds=[repeated, repeated, repeated],
            execution_coverage=1.0,
            noise_applicability=1.0,
        )


def test_sign_inconsistent_three_repeat_replay_extends_to_five() -> None:
    assert replay_action([0.1, -0.1, 0.2], repeats=3) == "extend_replay_to_5"
    assert replay_action([0.1, -0.1, 0.2], repeats=5) == "decide_candidate"


def test_screening_generalization_uses_fixed_three_seed_denominator() -> None:
    ready = decide_screening_generalization(
        seeds=[
            ScreeningSeedEvidence(
                method_seed=20260813,
                mean_delta_vs_seed=0.1,
                execution_complete=True,
                replay_count=3,
            ),
            ScreeningSeedEvidence(
                method_seed=20260814,
                mean_delta_vs_seed=0.0,
                execution_complete=True,
                replay_count=3,
            ),
            ScreeningSeedEvidence(
                method_seed=20260815,
                mean_delta_vs_seed=-0.01,
                execution_complete=True,
                replay_count=3,
            ),
        ],
        execution_coverage=1.0,
    )
    assert ready.status == "clean_generalization_ready"
    assert ready.nondegrading_seed_count == 2
    blocked = decide_screening_generalization(
        seeds=[
            ScreeningSeedEvidence(
                method_seed=seed,
                mean_delta_vs_seed=0.1,
                execution_complete=True,
                replay_count=3,
            )
            for seed in (20260813, 20260814, 20260815)
        ],
        execution_coverage=0.99,
    )
    assert blocked.status == "clean_generalization_failed"
    assert "incomplete_screening_execution_coverage" in blocked.failure_reasons

    zero_mean = decide_screening_generalization(
        seeds=[
            ScreeningSeedEvidence(
                method_seed=seed,
                mean_delta_vs_seed=delta,
                execution_complete=True,
                replay_count=3,
            )
            for seed, delta in zip(
                (20260813, 20260814, 20260815),
                (0.1, 0.0, -0.1),
                strict=True,
            )
        ],
        execution_coverage=1.0,
    )
    assert zero_mean.status == "clean_generalization_failed"
    assert "nonpositive_screening_mean_clean_gain" in zero_mean.failure_reasons


def test_mixed_or_missing_reuse_identity_requests_fixed_fallback_matrix() -> None:
    expected = {
        "baseline_fingerprint": "a" * 64,
        "evolution_input_hash": "b" * 64,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "provider_config_hash": "c" * 64,
        "method_seed": 20260813,
        "artifact_hash": "d" * 64,
    }
    assert reuse_action(expected, expected) == "reuse_artifact"
    mixed = {**expected, "baseline_fingerprint": "e" * 64}
    assert reuse_action(mixed, expected) == "run_fixed_fallback_matrix"
    missing = dict(expected)
    missing.pop("evolution_input_hash")
    assert reuse_action(missing, expected) == "run_fixed_fallback_matrix"


def test_spreadsheet_audit_requires_closed_headroom_and_mixed_batches() -> None:
    passed = audit_spreadsheet(
        validation_score=0.2,
        train_batches=[
            [True, False, False, False, False, False, False],
            [False, True, False, False, False, False, False],
            [False, False, True, False, False, False],
        ],
    )
    assert passed.passed is True
    assert (
        audit_spreadsheet(
            validation_score=0.81,
            train_batches=[[True, False, False]] * 3,
        ).passed
        is False
    )
    assert (
        audit_spreadsheet(
            validation_score=0.5,
            train_batches=[[True, True, True]] * 3,
        ).passed
        is False
    )


def test_officeqa_audit_requires_parseability_headroom_and_mixed_batches() -> None:
    passed = audit_officeqa(
        validation_score=0.75,
        parseable_answer_rate=0.9,
        train_batches=[[True, False, False, False]] * 3,
    )
    assert passed.passed is True
    assert (
        audit_officeqa(
            validation_score=0.5,
            parseable_answer_rate=0.89,
            train_batches=[[True, False, False, False]] * 3,
        ).passed
        is False
    )


def test_webshop_audit_requires_reachability_two_of_five_and_15_steps() -> None:
    passed = audit_webshop(
        target_reachable=[True] * 30,
        validation_outcomes=[True, False, True, False, False],
        max_episode_steps=15,
    )
    assert passed.passed is True
    assert (
        audit_webshop(
            target_reachable=[True, False],
            validation_outcomes=[True, False, True, False, False],
            max_episode_steps=15,
        ).passed
        is False
    )
    assert (
        audit_webshop(
            target_reachable=[True] * 30,
            validation_outcomes=[True, False, False, False, False],
            max_episode_steps=14,
        ).passed
        is False
    )


def test_skilllearn_audit_blocks_incomplete_verifier_or_hidden_test_leakage() -> None:
    ready = audit_skilllearn(
        executions=[
            {
                "container_started": True,
                "verifier_completed": True,
                "hidden_test_exposed": False,
            }
            for _ in range(3)
        ]
    )
    assert ready.passed is True
    leaked = audit_skilllearn(
        executions=[
            {
                "container_started": True,
                "verifier_completed": True,
                "hidden_test_exposed": True,
            }
        ]
    )
    assert leaked.passed is False
    assert "hidden_test_leakage" in leaked.failure_reasons


def test_incomplete_candidate_action_never_regresses_candidate_two_or_three() -> None:
    assert sequential_incomplete_action(1) == "rerun_candidate_1"
    assert sequential_incomplete_action(2) == "run_candidate_2"
    assert sequential_incomplete_action(3) == "clean_blocked_after_three_candidates"


def test_replay_integrity_rejects_two_repeats_and_malformed_resume_history() -> None:
    minimal = {
        "repeat_count": 2,
        "duration_seconds": 1.0,
        "task_ids": ["t1"],
        "artifact_hashes": {"seed": "a" * 64, "clean": "b" * 64},
        "observations": [],
        "summaries": {},
        "timing": {"run": {"level": "run"}, "stages": [], "tasks": []},
        "token_usage": {
            "observed_coverage": 1.0,
            "billed_tokens": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        },
        "resume_history": [],
    }
    assert "invalid_replay_repeat_count" in replay_integrity_failures(minimal)
    malformed_resume = {**minimal, "repeat_count": 5, "resume_history": []}
    assert "invalid_replay_resume_history" in replay_integrity_failures(
        malformed_resume
    )


def test_reduced_pool_candidate_denominator_is_rejected() -> None:
    def task(task_id: str) -> TaskManifest:
        return TaskManifest(
            task_id=task_id,
            benchmark="officeqa_full",
            domain="document",
            prompt=task_id,
            gold_answers=["answer"],
            source_hash=canonical_hash(task_id),
        )

    candidate = StableSplitCandidate(
        benchmark="officeqa_full",
        domain="document",
        candidate_index=2,
        train=[task("train-1"), task("train-2")],
        validation=[task("validation-1")],
        qualification_test=[task("qualification-1")],
        screening_test=[task("screening-1")],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="wrong fixed denominator"):
        validate_candidate_denominators(candidate)


def test_skilllearn_seed_group_rejects_mixed_fingerprint_and_family_substitution() -> (
    None
):
    candidate = StableSplitCandidate(
        benchmark="skilllearnbench",
        domain="skill_learning",
        candidate_index=1,
        train=[],
        validation=[],
        qualification_test=[],
        screening_test=[],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )

    def run(seed: int, *, family: str, fingerprint: str = "c" * 64):
        return CleanRunEvidence(
            benchmark="skilllearnbench",
            candidate_index=1,
            selection_hash=candidate.selection_hash,
            family=family,
            method_seed=seed,
            run_dir=f"/run/{seed}",
            train_task_ids=["train"],
            validation_task_ids=["validation"],
            accepted_update_count=1,
            artifact_changed=True,
            validation_complete=True,
            seed_artifact_path=f"/seed/{seed}",
            seed_artifact_hash="d" * 64,
            clean_artifact_path=f"/clean/{seed}",
            clean_artifact_hash="e" * 64,
            baseline_fingerprint=fingerprint,
            evolution_input_hash="f" * 64,
            provider="deepseek",
            model="deepseek-v4-flash",
            provider_config_hash="1" * 64,
        )

    records = [
        run(20260813, family="organize-messy-files"),
        run(
            20260814,
            family="organize-messy-files",
            fingerprint="9" * 64,
        ),
        run(20260815, family="substituted-family"),
    ]

    failures = _group_failures(
        candidate,
        records,
        family="organize-messy-files",
    )

    assert "mixed_clean_identity:baseline_fingerprint" in failures
    assert "run_family_substituted" in failures
