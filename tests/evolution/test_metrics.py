import pytest

from rsebench.evolution.metrics import compute_paired_metrics


def test_paired_metrics_compute_gains_gap_and_reverse_evolution():
    metrics = compute_paired_metrics(
        seed_scores={"a": 0.5, "b": 0.5},
        clean_scores={"a": 1.0, "b": 1.0},
        noisy_scores={"a": 0.0, "b": 0.5},
        bootstrap_samples=200,
        bootstrap_seed=7,
    )

    assert metrics.seed_score == pytest.approx(0.5)
    assert metrics.clean_evolved_score == pytest.approx(1.0)
    assert metrics.noisy_evolved_score == pytest.approx(0.25)
    assert metrics.clean_gain == pytest.approx(0.5)
    assert metrics.noisy_gain == pytest.approx(-0.25)
    assert metrics.evolution_gap == pytest.approx(0.75)
    assert metrics.reverse_evolution is True
    assert metrics.gap_ci_low <= metrics.evolution_gap <= metrics.gap_ci_high


def test_paired_metrics_require_identical_clean_test_ids():
    with pytest.raises(ValueError, match="task IDs"):
        compute_paired_metrics(
            seed_scores={"a": 1.0},
            clean_scores={"a": 1.0},
            noisy_scores={"b": 0.0},
        )
