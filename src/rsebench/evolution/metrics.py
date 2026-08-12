"""Metrics for clean-vs-noisy paired self-evolution."""

from __future__ import annotations

import random
from statistics import mean

from pydantic import Field

from rsebench.contracts import StrictModel


class PairedEvolutionMetrics(StrictModel):
    n_test: int = Field(ge=1)
    seed_score: float
    clean_evolved_score: float
    noisy_evolved_score: float
    clean_gain: float
    noisy_gain: float
    evolution_gap: float
    reverse_evolution: bool
    gap_ci_low: float
    gap_ci_high: float


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = fraction * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def compute_paired_metrics(
    *,
    seed_scores: dict[str, float],
    clean_scores: dict[str, float],
    noisy_scores: dict[str, float],
    bootstrap_samples: int = 2000,
    bootstrap_seed: int = 0,
) -> PairedEvolutionMetrics:
    ids = list(seed_scores)
    if not ids:
        raise ValueError("clean test scores must be non-empty")
    if set(ids) != set(clean_scores) or set(ids) != set(noisy_scores):
        raise ValueError("seed, clean, and noisy clean-test task IDs must match")
    seed_score = mean(float(seed_scores[task_id]) for task_id in ids)
    clean_score = mean(float(clean_scores[task_id]) for task_id in ids)
    noisy_score = mean(float(noisy_scores[task_id]) for task_id in ids)
    deltas = [
        float(clean_scores[task_id]) - float(noisy_scores[task_id])
        for task_id in ids
    ]
    rng = random.Random(bootstrap_seed)
    count = max(1, int(bootstrap_samples))
    boot = [
        mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
        for _ in range(count)
    ]
    return PairedEvolutionMetrics(
        n_test=len(ids),
        seed_score=seed_score,
        clean_evolved_score=clean_score,
        noisy_evolved_score=noisy_score,
        clean_gain=clean_score - seed_score,
        noisy_gain=noisy_score - seed_score,
        evolution_gap=clean_score - noisy_score,
        reverse_evolution=noisy_score < seed_score,
        gap_ci_low=_percentile(boot, 0.025),
        gap_ci_high=_percentile(boot, 0.975),
    )
