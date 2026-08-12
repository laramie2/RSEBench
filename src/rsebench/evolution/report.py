"""Human-readable reports for paired self-evolution runs."""

from __future__ import annotations

from rsebench.evolution.runner import PairedEvolutionResult


def render_paired_report(result: PairedEvolutionResult) -> str:
    metrics = result.metrics
    rows = [
        ("Method", result.method),
        ("Clean-test tasks", str(metrics.n_test)),
        ("Seed score", f"{metrics.seed_score:.4f}"),
        ("Clean-evolved score", f"{metrics.clean_evolved_score:.4f}"),
        ("Noisy-evolved score", f"{metrics.noisy_evolved_score:.4f}"),
        ("Clean gain", f"{metrics.clean_gain:+.4f}"),
        ("Noisy gain", f"{metrics.noisy_gain:+.4f}"),
        ("Evolution gap", f"{metrics.evolution_gap:.4f}"),
        (
            "Gap 95% paired bootstrap CI",
            f"[{metrics.gap_ci_low:.4f}, {metrics.gap_ci_high:.4f}]",
        ),
        ("Reverse evolution", "yes" if metrics.reverse_evolution else "no"),
    ]
    table = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return (
        "# Paired Self-Evolution Result\n\n"
        "Both evolution arms start from the same seed skill and are evaluated "
        "on the same untouched clean test split.\n\n"
        "| Metric | Value |\n"
        "|---|---:|\n"
        f"{table}\n"
    )
