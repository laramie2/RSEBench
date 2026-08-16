"""Apply the preregistered SkillFlow screening and qualification gates."""

from __future__ import annotations

from statistics import fmean
from typing import Literal, Sequence

from pydantic import Field

from rsebench.skillflow.contracts import FrozenStrictModel, REPLICATES
from rsebench.skillflow.results import SkillFlowReplicateResult


class SkillFlowFamilyDecision(FrozenStrictModel):
    family: str = Field(min_length=1)
    status: Literal["qualified", "not_qualified", "incomplete"]
    reasons: list[str]
    replicate_ids: list[str]
    positive_late_replicates: list[str]
    nonnegative_late_replicates: list[str]
    patch_replicates: list[str]
    skill_use_replicates: list[str]
    pooled_delta_full: float | None


def is_preliminary_positive(result: SkillFlowReplicateResult) -> bool:
    """Return whether one r1 pair is eligible for paid confirmation."""

    return bool(
        result.complete
        and result.delta_late is not None
        and result.delta_late > 0
        and result.evolution.nonempty_patch_count > 0
        and result.evolution.skill_used_task_count > 0
    )


def qualify_family(
    replicates: Sequence[SkillFlowReplicateResult],
) -> SkillFlowFamilyDecision:
    """Evaluate exactly r1/r2/r3 while keeping invalid runs out of efficacy."""

    reasons: list[str] = []
    ids = [item.replicate_id for item in replicates]
    family = replicates[0].family if replicates else "unknown"
    for replicate_id in REPLICATES:
        count = ids.count(replicate_id)
        if count == 0:
            reasons.append(f"missing_replicate:{replicate_id}")
        elif count > 1:
            reasons.append(f"duplicate_replicate:{replicate_id}")
    unexpected = sorted(set(ids) - set(REPLICATES))
    reasons.extend(f"unexpected_replicate:{item}" for item in unexpected)
    for item in replicates:
        if item.family != family:
            reasons.append(f"family_mismatch:{item.replicate_id}")
        if not item.complete:
            reasons.append(f"invalid_replicate:{item.replicate_id}")

    ordered = sorted(replicates, key=lambda item: REPLICATES.index(item.replicate_id))
    positive = [
        item.replicate_id
        for item in ordered
        if item.delta_late is not None and item.delta_late > 0
    ]
    nonnegative = [
        item.replicate_id
        for item in ordered
        if item.delta_late is not None and item.delta_late >= 0
    ]
    patch_replicates = [
        item.replicate_id for item in ordered if item.evolution.nonempty_patch_count > 0
    ]
    skill_use_replicates = [
        item.replicate_id for item in ordered if item.evolution.skill_used_task_count > 0
    ]

    structurally_complete = not reasons
    pooled_delta_full: float | None = None
    if structurally_complete:
        base_rewards = [reward for item in ordered for reward in item.base.task_rewards]
        evolution_rewards = [
            reward for item in ordered for reward in item.evolution.task_rewards
        ]
        pooled_delta_full = fmean(evolution_rewards) - fmean(base_rewards)
        if len(positive) < 2:
            reasons.append(f"insufficient_positive_late_replicates:{len(positive)}<2")
        for item in ordered:
            if item.delta_late is not None and item.delta_late < 0:
                reasons.append(f"late_delta_negative:{item.replicate_id}")
        for item in ordered:
            if item.evolution.nonempty_patch_count == 0:
                reasons.append(f"missing_nonempty_patch:{item.replicate_id}")
        if len(skill_use_replicates) < 2:
            reasons.append(
                f"insufficient_skill_use_replicates:{len(skill_use_replicates)}<2"
            )
        if pooled_delta_full <= 0:
            reasons.append(f"pooled_full_delta_not_positive:{pooled_delta_full:.6f}")

    if not structurally_complete:
        status: Literal["qualified", "not_qualified", "incomplete"] = "incomplete"
    elif reasons:
        status = "not_qualified"
    else:
        status = "qualified"
    return SkillFlowFamilyDecision(
        family=family,
        status=status,
        reasons=list(dict.fromkeys(reasons)),
        replicate_ids=ids,
        positive_late_replicates=positive,
        nonnegative_late_replicates=nonnegative,
        patch_replicates=patch_replicates,
        skill_use_replicates=skill_use_replicates,
        pooled_delta_full=pooled_delta_full,
    )


__all__ = ["SkillFlowFamilyDecision", "is_preliminary_positive", "qualify_family"]
