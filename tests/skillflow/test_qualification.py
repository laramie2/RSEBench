from __future__ import annotations

from datetime import datetime, timezone

from rsebench.skillflow.qualification import is_preliminary_positive, qualify_family
from rsebench.skillflow.results import (
    SkillFlowArmResult,
    SkillFlowReplicateResult,
    SkillFlowTaskResult,
    SkillFlowTokenUsage,
)


NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _arm(
    replicate_id: str,
    arm: str,
    rewards: list[float],
    *,
    complete: bool = True,
    patch: bool = False,
    skill_use: bool = False,
) -> SkillFlowArmResult:
    tasks = [
        SkillFlowTaskResult(
            task_id=f"task-{index + 1}",
            order=index + 1,
            reward=reward,
            task_checksum=f"checksum-{index + 1}",
            started_at=NOW,
            finished_at=NOW,
            duration_seconds=0.0,
            agent_duration_seconds=0.0,
            verifier_duration_seconds=0.0,
            patch_duration_seconds=0.0 if patch else None,
            skill_use_calls=1 if skill_use and index == 1 else 0,
            skills_used=["shared"] if skill_use and index == 1 else [],
            exception_type=None,
        )
        for index, reward in enumerate(rewards)
    ]
    return SkillFlowArmResult(
        family="Example-Family",
        replicate_id=replicate_id,
        arm=arm,
        complete=complete,
        invalid_reasons=[] if complete else ["provider_failure"],
        task_results=tasks,
        task_rewards=rewards,
        patch_count=len(tasks) if patch else 0,
        nonempty_patch_count=len(tasks) if patch else 0,
        skill_used_task_count=1 if skill_use else 0,
        started_at=NOW,
        finished_at=NOW,
        duration_seconds=0.0,
        token_usage=SkillFlowTokenUsage(
            attempted_calls=1,
            observed_calls=1,
            observed_coverage=1.0,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        ),
    )


def _replicate(
    replicate_id: str,
    delta_late: float,
    *,
    delta_full: float | None = None,
    valid: bool = True,
    patch: bool = True,
    skill_use: bool = True,
) -> SkillFlowReplicateResult:
    base_rewards = [0.0, 0.5]
    evolution_rewards = [
        (delta_full if delta_full is not None else delta_late),
        0.5 + delta_late,
    ]
    base = _arm(replicate_id, "base", base_rewards)
    evolution = _arm(
        replicate_id,
        "clean_evolution",
        evolution_rewards,
        complete=valid,
        patch=patch,
        skill_use=skill_use,
    )
    return SkillFlowReplicateResult(
        family="Example-Family",
        replicate_id=replicate_id,
        complete=valid,
        invalid_reasons=[] if valid else ["clean_evolution:provider_failure"],
        base=base,
        evolution=evolution,
        delta_late=delta_late if valid else None,
        delta_full=(
            sum(evolution_rewards) / 2 - sum(base_rewards) / 2 if valid else None
        ),
    )


def test_two_positive_and_one_tie_qualifies() -> None:
    decision = qualify_family(
        [_replicate("r1", 0.5), _replicate("r2", 0.25), _replicate("r3", 0.0)]
    )

    assert decision.status == "qualified"
    assert decision.positive_late_replicates == ["r1", "r2"]
    assert decision.nonnegative_late_replicates == ["r1", "r2", "r3"]
    assert decision.pooled_delta_full > 0


def test_one_negative_replicate_does_not_qualify() -> None:
    decision = qualify_family(
        [_replicate("r1", 0.5), _replicate("r2", 0.25), _replicate("r3", -0.25)]
    )

    assert decision.status == "not_qualified"
    assert "late_delta_negative:r3" in decision.reasons


def test_only_one_positive_replicate_does_not_qualify() -> None:
    decision = qualify_family(
        [_replicate("r1", 0.5), _replicate("r2", 0.0), _replicate("r3", 0.0)]
    )

    assert decision.status == "not_qualified"
    assert "insufficient_positive_late_replicates:1<2" in decision.reasons


def test_invalid_replicate_is_incomplete_not_negative() -> None:
    decision = qualify_family(
        [
            _replicate("r1", 0.5),
            _replicate("r2", 0.25),
            _replicate("r3", 0.0, valid=False),
        ]
    )

    assert decision.status == "incomplete"
    assert "invalid_replicate:r3" in decision.reasons


def test_missing_patch_or_skill_use_fails_gate() -> None:
    patch_decision = qualify_family(
        [
            _replicate("r1", 0.5),
            _replicate("r2", 0.25, patch=False),
            _replicate("r3", 0.0),
        ]
    )
    skill_decision = qualify_family(
        [
            _replicate("r1", 0.5),
            _replicate("r2", 0.25, skill_use=False),
            _replicate("r3", 0.0, skill_use=False),
        ]
    )

    assert patch_decision.status == "not_qualified"
    assert "missing_nonempty_patch:r2" in patch_decision.reasons
    assert skill_decision.status == "not_qualified"
    assert "insufficient_skill_use_replicates:1<2" in skill_decision.reasons


def test_duplicate_or_missing_replicates_are_incomplete() -> None:
    missing = qualify_family([_replicate("r1", 0.5), _replicate("r2", 0.25)])
    duplicate = qualify_family(
        [_replicate("r1", 0.5), _replicate("r1", 0.25), _replicate("r3", 0.0)]
    )

    assert missing.status == "incomplete"
    assert "missing_replicate:r3" in missing.reasons
    assert duplicate.status == "incomplete"
    assert "duplicate_replicate:r1" in duplicate.reasons


def test_preliminary_positive_requires_gain_patch_and_later_skill_use() -> None:
    assert is_preliminary_positive(_replicate("r1", 0.5)) is True
    assert is_preliminary_positive(_replicate("r1", 0.0)) is False
    assert is_preliminary_positive(_replicate("r1", 0.5, patch=False)) is False
    assert is_preliminary_positive(_replicate("r1", 0.5, skill_use=False)) is False


def test_nonpositive_pooled_full_delta_fails_gate() -> None:
    decision = qualify_family(
        [
            _replicate("r1", 1.0, delta_full=-2.0),
            _replicate("r2", 1.0, delta_full=-2.0),
            _replicate("r3", 0.0, delta_full=0.0),
        ]
    )

    assert decision.status == "not_qualified"
    assert any(reason.startswith("pooled_full_delta_not_positive:") for reason in decision.reasons)
