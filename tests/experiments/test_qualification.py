from __future__ import annotations

import pytest

from rsebench.experiments.qualification import (
    SeedReadiness,
    aggregate_cell_readiness,
)


SEEDS = (20260813, 20260814, 20260815)


def _seed(
    method_seed: int,
    *,
    engineering_valid: bool,
    clean_gain: float,
    identity_family_hash: str = "a" * 64,
) -> SeedReadiness:
    return SeedReadiness(
        method_seed=method_seed,
        status="completed",
        identity_family_hash=identity_family_hash,
        experiment_id=f"{method_seed:064x}"[-64:],
        engineering_valid=engineering_valid,
        clean_gain=clean_gain,
        positive_gain=engineering_valid and clean_gain > 0,
        accepted_update_count=1 if engineering_valid else 0,
        failure_reasons=[] if engineering_valid else ["no_accepted_update"],
    )


def test_two_engineering_valid_and_positive_seeds_pass_both_gates() -> None:
    readiness = aggregate_cell_readiness(
        [
            _seed(SEEDS[0], engineering_valid=True, clean_gain=0.1),
            _seed(SEEDS[1], engineering_valid=True, clean_gain=0.2),
            _seed(SEEDS[2], engineering_valid=False, clean_gain=0.0),
        ],
        expected_seeds=SEEDS,
    )

    assert readiness.engineering_valid_seeds == list(SEEDS[:2])
    assert readiness.positive_gain_seeds == list(SEEDS[:2])
    assert readiness.engineering_ready is True
    assert readiness.efficacy_ready is True


def test_engineering_can_pass_without_efficacy() -> None:
    readiness = aggregate_cell_readiness(
        [
            _seed(seed, engineering_valid=True, clean_gain=0.0)
            for seed in SEEDS
        ],
        expected_seeds=SEEDS,
    )

    assert readiness.engineering_ready is True
    assert readiness.efficacy_ready is False
    assert readiness.positive_gain_seeds == []
    assert "insufficient_positive_gain_seeds" in readiness.failure_reasons


def test_mixed_identity_families_are_rejected() -> None:
    with pytest.raises(ValueError, match="identity families"):
        aggregate_cell_readiness(
            [
                _seed(SEEDS[0], engineering_valid=True, clean_gain=0.1),
                _seed(
                    SEEDS[1],
                    engineering_valid=True,
                    clean_gain=0.1,
                    identity_family_hash="b" * 64,
                ),
            ],
            expected_seeds=SEEDS,
        )


def test_missing_seed_stays_in_fixed_denominator() -> None:
    readiness = aggregate_cell_readiness(
        [
            _seed(SEEDS[0], engineering_valid=True, clean_gain=0.1),
            _seed(SEEDS[1], engineering_valid=False, clean_gain=0.0),
        ],
        expected_seeds=SEEDS,
    )

    assert readiness.engineering_ready is False
    assert readiness.efficacy_ready is False
    assert readiness.seed_results[2].status == "missing"
    assert f"missing_seed:{SEEDS[2]}" in readiness.failure_reasons
