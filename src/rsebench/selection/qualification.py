"""Fail-closed qualification rules for frozen clean selection artifacts."""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field

from rsebench.contracts import StrictModel
from rsebench.evolution.artifact_evaluation import RepeatedArtifactReplayResult
from rsebench.selection.contracts import (
    CandidateDecision,
    CandidateSeedEvidence,
    ScreeningGeneralizationDecision,
    ScreeningSeedEvidence,
    StableSplitCandidate,
)


class DomainQualificationAudit(StrictModel):
    """Typed structural gate result used before any selection decision."""

    passed: bool
    execution_coverage: float = Field(ge=0.0, le=1.0)
    failure_reasons: list[str] = Field(default_factory=list)


class DomainScreeningGeneralization(StrictModel):
    status: Literal["clean_generalization_ready", "clean_generalization_failed"]
    decision: ScreeningGeneralizationDecision | None = None
    ready_families: list[str] = Field(default_factory=list)
    family_decisions: dict[str, ScreeningGeneralizationDecision] = Field(
        default_factory=dict
    )
    failure_reasons: list[str] = Field(default_factory=list)


class ScreeningGeneralizationAggregate(StrictModel):
    schema_version: str = "rsebench.screening-generalization.v1"
    domains: dict[str, DomainScreeningGeneralization]
    all_ready: bool


_POOL_EVALUATION_COUNTS = {
    "spreadsheetbench_verified": 30,
    "officeqa_full": 20,
    "webshop": 20,
}


def select_candidate_evaluation_tasks(
    candidate: StableSplitCandidate,
    *,
    evaluation_role: Literal["qualification_test", "screening_test"],
    family: str | None = None,
) -> list[Any]:
    """Select the exact frozen evaluation role without permitting role aliasing."""

    tasks = list(getattr(candidate, evaluation_role))
    if candidate.benchmark == "skilllearnbench":
        if evaluation_role == "qualification_test":
            raise ValueError("SkillLearn has no qualification replay")
        if not family:
            raise ValueError("SkillLearn screening replay requires a family")
        tasks = [
            task
            for task in tasks
            if str(task.metadata.get("task_family") or "") == family
        ]
        allocations = candidate.metadata.get("static_audit", {}).get(
            "family_allocations", {}
        )
        expected = allocations.get(family, {}).get("screening_test")
        if [task.task_id for task in tasks] != expected:
            raise ValueError(f"SkillLearn screening allocation differs: {family}")
        if len(tasks) not in {2, 3}:
            raise ValueError("SkillLearn screening family requires 2 or 3 tasks")
        return tasks
    if family is not None:
        raise ValueError("family selector is only valid for SkillLearn")
    expected_count = _POOL_EVALUATION_COUNTS.get(candidate.benchmark)
    if expected_count is None:
        raise ValueError(f"unsupported selection benchmark: {candidate.benchmark}")
    if len(tasks) != expected_count:
        raise ValueError(
            f"{candidate.benchmark} {evaluation_role} requires exactly "
            f"{expected_count} tasks"
        )
    return tasks


def _mixed_batch_failures(
    batches: Sequence[Sequence[bool]],
    *,
    expected_sizes: Sequence[int],
) -> list[str]:
    if [len(batch) for batch in batches] != list(expected_sizes):
        return ["unexpected_train_batch_denominator"]
    failures: list[str] = []
    for index, batch in enumerate(batches, start=1):
        successes = sum(bool(outcome) for outcome in batch)
        ordinary_failures = len(batch) - successes
        if successes < 1 or ordinary_failures < 2:
            failures.append(f"train_batch_not_mixed:{index}")
    return failures


def audit_spreadsheet(
    *,
    validation_score: float,
    train_batches: Sequence[Sequence[bool]],
) -> DomainQualificationAudit:
    reasons = _mixed_batch_failures(train_batches, expected_sizes=(7, 7, 6))
    if not 0.2 <= validation_score <= 0.8:
        reasons.append("spreadsheet_validation_headroom_out_of_range")
    return DomainQualificationAudit(
        passed=not reasons,
        execution_coverage=1.0,
        failure_reasons=reasons,
    )


def audit_officeqa(
    *,
    validation_score: float,
    parseable_answer_rate: float,
    train_batches: Sequence[Sequence[bool]],
) -> DomainQualificationAudit:
    reasons = _mixed_batch_failures(train_batches, expected_sizes=(4, 4, 4))
    if parseable_answer_rate < 0.9:
        reasons.append("officeqa_parseable_answer_rate_below_0.9")
    if not 0.25 <= validation_score <= 0.75:
        reasons.append("officeqa_validation_headroom_out_of_range")
    return DomainQualificationAudit(
        passed=not reasons,
        execution_coverage=1.0,
        failure_reasons=reasons,
    )


def audit_webshop(
    *,
    target_reachable: Sequence[bool],
    validation_outcomes: Sequence[bool],
    max_episode_steps: int,
) -> DomainQualificationAudit:
    reasons: list[str] = []
    if len(target_reachable) != 30:
        reasons.append("unexpected_webshop_task_denominator")
    if not target_reachable or not all(target_reachable):
        reasons.append("unreachable_webshop_target")
    if len(validation_outcomes) != 5 or sum(validation_outcomes) != 2:
        reasons.append("webshop_validation_headroom_not_2_of_5")
    if max_episode_steps != 15:
        reasons.append("webshop_step_budget_not_15")
    return DomainQualificationAudit(
        passed=not reasons,
        execution_coverage=1.0,
        failure_reasons=reasons,
    )


def audit_skilllearn(
    *,
    executions: Sequence[Mapping[str, Any]],
) -> DomainQualificationAudit:
    reasons: list[str] = []
    if len(executions) != 3:
        reasons.append("unexpected_skilllearn_execution_denominator")
    if not executions or not all(
        row.get("container_started") is True for row in executions
    ):
        reasons.append("skilllearn_container_incomplete")
    if not executions or not all(
        row.get("verifier_completed") is True for row in executions
    ):
        reasons.append("skilllearn_verifier_incomplete")
    if any(row.get("hidden_test_exposed") is not False for row in executions):
        reasons.append("hidden_test_leakage")
    coverage = (
        sum(
            row.get("container_started") is True
            and row.get("verifier_completed") is True
            for row in executions
        )
        / 3
        if executions
        else 0.0
    )
    return DomainQualificationAudit(
        passed=not reasons,
        execution_coverage=min(1.0, coverage),
        failure_reasons=reasons,
    )


def replay_action(
    deltas: Sequence[float], *, repeats: int
) -> Literal["extend_replay_to_5", "decide_candidate"]:
    if not deltas:
        raise ValueError("replay action requires paired deltas")
    if repeats not in {3, 5}:
        raise ValueError("replay action supports exactly three or five repeats")
    if repeats == 3 and min(deltas) < 0.0 < max(deltas):
        return "extend_replay_to_5"
    return "decide_candidate"


def sequential_incomplete_action(
    candidate_index: int,
) -> Literal[
    "rerun_candidate_1",
    "run_candidate_2",
    "clean_blocked_after_three_candidates",
]:
    """Return the only legal action for incomplete evidence at one candidate."""

    if candidate_index == 1:
        return "rerun_candidate_1"
    if candidate_index == 2:
        return "run_candidate_2"
    if candidate_index == 3:
        return "clean_blocked_after_three_candidates"
    raise ValueError("candidate index must be one of 1, 2, or 3")


def decision_failures(
    *,
    seeds: Sequence[CandidateSeedEvidence],
    execution_coverage: float,
    noise_applicability: float,
) -> list[str]:
    reasons: list[str] = []
    accepted = sum(
        row.accepted_update_count > 0 and row.artifact_changed for row in seeds
    )
    nondegrading = sum(row.mean_delta_vs_seed >= 0.0 for row in seeds)
    mean_gain = statistics.fmean(row.mean_delta_vs_seed for row in seeds)
    if accepted < 2:
        reasons.append("fewer_than_two_accepted_artifact_updates")
    if nondegrading < 2:
        reasons.append("fewer_than_two_nondegrading_seed_replays")
    if mean_gain <= 0.0:
        reasons.append("nonpositive_mean_clean_gain")
    if execution_coverage != 1.0:
        reasons.append("incomplete_execution_coverage")
    if noise_applicability != 1.0:
        reasons.append("incomplete_noise_applicability")
    if not all(row.execution_complete for row in seeds):
        reasons.append("incomplete_seed_execution")
    return reasons


def decide_candidate(
    *,
    candidate_index: int,
    seeds: Sequence[CandidateSeedEvidence],
    execution_coverage: float,
    noise_applicability: float,
) -> CandidateDecision:
    if len(seeds) != 3 or len({row.method_seed for row in seeds}) != 3:
        raise ValueError("candidate decision requires exactly three unique seeds")
    if candidate_index not in {1, 2, 3}:
        raise ValueError("candidate index must be one of 1, 2, or 3")
    accepted = [
        row for row in seeds if row.accepted_update_count > 0 and row.artifact_changed
    ]
    nondegrading = [row for row in seeds if row.mean_delta_vs_seed >= 0.0]
    mean_gain = statistics.fmean(row.mean_delta_vs_seed for row in seeds)
    passed = (
        len(accepted) >= 2
        and len(nondegrading) >= 2
        and mean_gain > 0.0
        and execution_coverage == 1.0
        and noise_applicability == 1.0
        and all(row.execution_complete for row in seeds)
    )
    if passed:
        next_action = "freeze_candidate"
    elif candidate_index < 3:
        next_action = f"run_candidate_{candidate_index + 1}"
    else:
        next_action = "clean_blocked_after_three_candidates"
    return CandidateDecision(
        candidate_index=candidate_index,
        passed=passed,
        accepted_seed_count=len(accepted),
        nondegrading_seed_count=len(nondegrading),
        mean_clean_gain=mean_gain,
        execution_coverage=execution_coverage,
        noise_applicability=noise_applicability,
        next_action=next_action,
        failure_reasons=decision_failures(
            seeds=seeds,
            execution_coverage=execution_coverage,
            noise_applicability=noise_applicability,
        ),
    )


def decide_screening_generalization(
    *,
    seeds: Sequence[ScreeningSeedEvidence],
    execution_coverage: float,
) -> ScreeningGeneralizationDecision:
    if len(seeds) != 3 or len({row.method_seed for row in seeds}) != 3:
        raise ValueError("screening decision requires exactly three unique seeds")
    nondegrading = sum(row.mean_delta_vs_seed >= 0.0 for row in seeds)
    mean_gain = statistics.fmean(row.mean_delta_vs_seed for row in seeds)
    ready = (
        nondegrading >= 2
        and mean_gain > 0.0
        and execution_coverage == 1.0
        and all(row.execution_complete for row in seeds)
    )
    reasons: list[str] = []
    if nondegrading < 2:
        reasons.append("fewer_than_two_nondegrading_screening_replays")
    if mean_gain <= 0.0:
        reasons.append("nonpositive_screening_mean_clean_gain")
    if execution_coverage != 1.0 or not all(row.execution_complete for row in seeds):
        reasons.append("incomplete_screening_execution_coverage")
    return ScreeningGeneralizationDecision(
        status=(
            "clean_generalization_ready" if ready else "clean_generalization_failed"
        ),
        nondegrading_seed_count=nondegrading,
        mean_clean_gain=mean_gain,
        execution_coverage=execution_coverage,
        failure_reasons=reasons,
    )


_REUSE_FIELDS = (
    "baseline_fingerprint",
    "evolution_input_hash",
    "provider",
    "model",
    "provider_config_hash",
    "method_seed",
    "artifact_hash",
)


def reuse_action(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> Literal["reuse_artifact", "run_fixed_fallback_matrix"]:
    """Approve artifact reuse only when every preregistered identity field matches."""

    for field in _REUSE_FIELDS:
        if field not in actual or field not in expected:
            return "run_fixed_fallback_matrix"
        if actual[field] != expected[field]:
            return "run_fixed_fallback_matrix"
    return "reuse_artifact"


def replay_integrity_failures(
    replay: Mapping[str, Any],
) -> list[str]:
    """Validate the accounting fields required before replay aggregation."""

    failures: list[str] = []
    repeat_count = replay.get("repeat_count")
    if repeat_count not in {3, 5}:
        failures.append("invalid_replay_repeat_count")
    resume_history = replay.get("resume_history")
    if repeat_count == 3 and resume_history not in ([], None):
        failures.append("invalid_replay_resume_history")
    if repeat_count == 5:
        if (
            not isinstance(resume_history, list)
            or len(resume_history) != 1
            or not isinstance(resume_history[0], Mapping)
            or resume_history[0].get("from_repeat_count") != 3
            or resume_history[0].get("to_repeat_count") != 5
        ):
            failures.append("invalid_replay_resume_history")
    try:
        RepeatedArtifactReplayResult.model_validate(replay)
    except Exception:
        failures.append("malformed_replay_result")
    duration = replay.get("duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or duration < 0
    ):
        failures.append("missing_run_wall_time")
    timing = replay.get("timing")
    if not isinstance(timing, Mapping):
        failures.append("missing_replay_timing")
    else:
        run = timing.get("run")
        stages = timing.get("stages")
        tasks = timing.get("tasks")
        if not isinstance(run, Mapping) or run.get("level") != "run":
            failures.append("missing_run_timing")
        if not isinstance(stages, list) or not stages:
            failures.append("missing_stage_timing")
        if not isinstance(tasks, list) or not tasks:
            failures.append("missing_task_timing")
        task_ids = replay.get("task_ids")
        artifact_hashes = replay.get("artifact_hashes")
        if (
            isinstance(repeat_count, int)
            and isinstance(task_ids, list)
            and isinstance(artifact_hashes, Mapping)
            and isinstance(stages, list)
            and isinstance(tasks, list)
        ):
            expected_stages = repeat_count * len(artifact_hashes)
            expected_tasks = expected_stages * len(task_ids)
            if len(stages) != expected_stages:
                failures.append("incomplete_stage_timing_denominator")
            if len(tasks) != expected_tasks:
                failures.append("incomplete_task_timing_denominator")
            observations = replay.get("observations")
            if (
                not isinstance(observations, list)
                or len(observations) != expected_stages
            ):
                failures.append("incomplete_replay_observation_denominator")
            else:
                expected_pairs = {
                    (repeat, label)
                    for repeat in range(1, repeat_count + 1)
                    for label in artifact_hashes
                }
                observed_pairs = {
                    (observation.get("repeat"), observation.get("artifact_label"))
                    for observation in observations
                    if isinstance(observation, Mapping)
                }
                if observed_pairs != expected_pairs:
                    failures.append("incomplete_replay_observation_denominator")
                expected_task_ids = set(task_ids)
                for observation in observations:
                    evaluation = (
                        observation.get("evaluation")
                        if isinstance(observation, Mapping)
                        else None
                    )
                    scores = (
                        evaluation.get("per_task_scores")
                        if isinstance(evaluation, Mapping)
                        else None
                    )
                    if (
                        not isinstance(scores, Mapping)
                        or set(scores) != expected_task_ids
                    ):
                        failures.append("incomplete_replay_task_scores")
                        break
            summaries = replay.get("summaries")
            if not isinstance(summaries, Mapping) or set(summaries) != set(
                artifact_hashes
            ):
                failures.append("incomplete_replay_summaries")
            elif any(
                not isinstance(summary, Mapping)
                or len(summary.get("scores", [])) != repeat_count
                or len(summary.get("deltas_vs_reference", [])) != repeat_count
                for summary in summaries.values()
            ):
                failures.append("incomplete_replay_summary_denominator")
    usage = replay.get("token_usage")
    if not isinstance(usage, Mapping):
        failures.append("missing_token_usage")
    else:
        billed = usage.get("billed_tokens")
        if not isinstance(billed, Mapping) or any(
            field not in billed
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        ):
            failures.append("missing_token_totals")
        elif billed["total_tokens"] != (
            billed["prompt_tokens"] + billed["completion_tokens"]
        ):
            failures.append("inconsistent_token_totals")
        if usage.get("observed_coverage") != 1.0:
            failures.append("incomplete_token_observation")
    return list(dict.fromkeys(failures))


__all__ = [
    "DomainQualificationAudit",
    "DomainScreeningGeneralization",
    "ScreeningGeneralizationAggregate",
    "audit_officeqa",
    "audit_skilllearn",
    "audit_spreadsheet",
    "audit_webshop",
    "decide_candidate",
    "decide_screening_generalization",
    "decision_failures",
    "replay_action",
    "replay_integrity_failures",
    "reuse_action",
    "sequential_incomplete_action",
    "select_candidate_evaluation_tasks",
]
