"""Fixed-denominator clean engineering and efficacy readiness."""

from __future__ import annotations

from typing import Literal, Sequence

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel


class SeedReadiness(StrictModel):
    method_seed: int
    status: Literal["completed", "missing", "failed", "interrupted", "invalid"]
    identity_family_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    experiment_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    engineering_valid: bool = False
    clean_gain: float | None = None
    positive_gain: bool = False
    accepted_update_count: int = Field(default=0, ge=0)
    seed_score: float | None = None
    evolved_score: float | None = None
    failure_reasons: list[str] = Field(default_factory=list)
    run_id: str | None = None
    path: str | None = None
    config_version: str | None = None

    @model_validator(mode="after")
    def validate_readiness(self) -> "SeedReadiness":
        if self.status == "completed":
            if self.identity_family_hash is None or self.experiment_id is None:
                raise ValueError("completed seed requires experiment identity")
            if self.clean_gain is None:
                raise ValueError("completed seed requires clean gain")
        elif self.engineering_valid or self.positive_gain:
            raise ValueError("incomplete seed cannot be readiness-valid")
        if self.positive_gain and (
            not self.engineering_valid
            or self.clean_gain is None
            or self.clean_gain <= 0
        ):
            raise ValueError("positive gain requires an engineering-valid positive run")
        return self


class CellReadiness(StrictModel):
    expected_seeds: list[int]
    engineering_valid_seeds: list[int]
    positive_gain_seeds: list[int]
    engineering_ready: bool
    efficacy_ready: bool
    failure_reasons: list[str]
    seed_results: list[SeedReadiness]


def aggregate_cell_readiness(
    results: Sequence[SeedReadiness],
    *,
    expected_seeds: Sequence[int] = (20260813, 20260814, 20260815),
) -> CellReadiness:
    """Apply the immutable 2/3 denominator without replacing failed seeds."""

    expected = list(expected_seeds)
    if len(expected) != len(set(expected)):
        raise ValueError("expected method seeds must be unique")
    by_seed: dict[int, SeedReadiness] = {}
    for result in results:
        if result.method_seed not in expected:
            raise ValueError(f"unexpected method seed: {result.method_seed}")
        if result.method_seed in by_seed:
            raise ValueError(f"duplicate method seed: {result.method_seed}")
        by_seed[result.method_seed] = result

    completed_families = {
        result.identity_family_hash
        for result in by_seed.values()
        if result.status == "completed"
    }
    if len(completed_families) > 1:
        raise ValueError("completed seeds belong to mixed experiment identity families")

    ordered: list[SeedReadiness] = []
    failure_reasons: list[str] = []
    for method_seed in expected:
        result = by_seed.get(method_seed)
        if result is None:
            result = SeedReadiness(
                method_seed=method_seed,
                status="missing",
                failure_reasons=["missing_seed"],
            )
            failure_reasons.append(f"missing_seed:{method_seed}")
        else:
            failure_reasons.extend(
                f"seed_{method_seed}:{reason}" for reason in result.failure_reasons
            )
        ordered.append(result)

    engineering_valid_seeds = [
        result.method_seed for result in ordered if result.engineering_valid
    ]
    positive_gain_seeds = [
        result.method_seed for result in ordered if result.positive_gain
    ]
    engineering_ready = len(engineering_valid_seeds) >= 2
    efficacy_ready = engineering_ready and len(positive_gain_seeds) >= 2
    if not engineering_ready:
        failure_reasons.append("insufficient_engineering_valid_seeds")
    if len(positive_gain_seeds) < 2:
        failure_reasons.append("insufficient_positive_gain_seeds")
    return CellReadiness(
        expected_seeds=expected,
        engineering_valid_seeds=engineering_valid_seeds,
        positive_gain_seeds=positive_gain_seeds,
        engineering_ready=engineering_ready,
        efficacy_ready=efficacy_ready,
        failure_reasons=list(dict.fromkeys(failure_reasons)),
        seed_results=ordered,
    )


__all__ = ["CellReadiness", "SeedReadiness", "aggregate_cell_readiness"]
