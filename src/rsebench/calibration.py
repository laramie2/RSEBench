"""Paper-facing acceptance gates for candidate benchmark operators."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OperatorMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    structural_rate: float = Field(ge=0, le=1)
    label_invariance_rate: float = Field(ge=0, le=1)
    applicability_rate: float = Field(ge=0, le=1)
    leakage_rate: float = Field(ge=0, le=1)
    clean_score: float = Field(ge=0, le=1)
    noisy_l1_score: float = Field(ge=0, le=1)
    noisy_l2_score: float = Field(ge=0, le=1)
    noisy_l3_score: float = Field(ge=0, le=1)


class PilotDecision(BaseModel):
    accepted: bool
    failed_gates: list[str]
    effect_l2: float
    floor_ratio_l3: float
    severity_monotonic: bool


def evaluate_operator_gates(
    metrics: OperatorMetrics,
    *,
    minimum_applicability: float = 0.8,
    minimum_l2_drop: float = 0.05,
    minimum_floor_ratio: float = 0.2,
    monotonic_tolerance: float = 0.02,
) -> PilotDecision:
    failed: list[str] = []
    if metrics.structural_rate < 1.0:
        failed.append("structural_validity")
    if metrics.label_invariance_rate < 1.0:
        failed.append("label_invariance")
    if metrics.leakage_rate > 0.0:
        failed.append("answer_leakage")
    if metrics.applicability_rate < minimum_applicability:
        failed.append("applicability")
    effect = metrics.clean_score - metrics.noisy_l2_score
    if effect < minimum_l2_drop:
        failed.append("minimum_effect")
    floor_ratio = (
        metrics.noisy_l3_score / metrics.clean_score
        if metrics.clean_score > 0
        else 0.0
    )
    if floor_ratio < minimum_floor_ratio:
        failed.append("floor_avoidance")
    scores = [
        metrics.clean_score,
        metrics.noisy_l1_score,
        metrics.noisy_l2_score,
        metrics.noisy_l3_score,
    ]
    monotonic = all(
        later <= earlier + monotonic_tolerance
        for earlier, later in zip(scores, scores[1:])
    )
    if not monotonic:
        failed.append("severity_monotonicity")
    return PilotDecision(
        accepted=not failed,
        failed_gates=failed,
        effect_l2=effect,
        floor_ratio_l3=floor_ratio,
        severity_monotonic=monotonic,
    )
