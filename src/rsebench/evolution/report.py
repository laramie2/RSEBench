"""Human-readable reports for paired self-evolution runs."""

from __future__ import annotations

from rsebench.evolution.artifact_evaluation import ArtifactComparisonResult
from rsebench.evolution.runner import PairedEvolutionResult


def render_paired_report(result: PairedEvolutionResult) -> str:
    metrics = result.metrics
    billed = result.token_usage["billed_tokens"]
    logical = result.token_usage["logical_tokens"]
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
        ("Billed tokens", str(billed["total_tokens"])),
        ("Logical tokens", str(logical["total_tokens"])),
        ("Token coverage", f"{result.token_usage['observed_coverage']:.4f}"),
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


def render_artifact_comparison(result: ArtifactComparisonResult) -> str:
    """Render expanded clean-test evidence for fixed skill artifacts."""

    metrics = result.metrics
    transitions = result.transitions
    billed = result.token_usage["billed_tokens"]
    logical = result.token_usage["logical_tokens"]
    rows = [
        ("Clean-test tasks", str(metrics.n_test)),
        ("Seed score", f"{metrics.seed_score:.4f}"),
        ("Clean-evolved score", f"{metrics.clean_evolved_score:.4f}"),
        ("Noisy-evolved score", f"{metrics.noisy_evolved_score:.4f}"),
        ("Clean gain", f"{metrics.clean_gain:+.4f}"),
        ("Noisy gain", f"{metrics.noisy_gain:+.4f}"),
        ("Evolution gap", f"{metrics.evolution_gap:+.4f}"),
        (
            "Gap 95% paired bootstrap CI",
            f"[{metrics.gap_ci_low:.4f}, {metrics.gap_ci_high:.4f}]",
        ),
        ("Clean-correct / noisy-wrong", str(transitions.clean_correct_noisy_wrong)),
        ("Clean-wrong / noisy-correct", str(transitions.clean_wrong_noisy_correct)),
        ("Net harmful flips", str(transitions.net_harmful_flips)),
        ("Reverse evolution", "yes" if metrics.reverse_evolution else "no"),
        ("Billed tokens", str(billed["total_tokens"])),
        ("Logical tokens", str(logical["total_tokens"])),
        ("Token coverage", f"{result.token_usage['observed_coverage']:.4f}"),
    ]
    table = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return (
        "# Expanded Artifact Evaluation\n\n"
        "The fixed seed, clean-evolved, and noisy-evolved skills are evaluated "
        "on the same expanded untouched clean test split.\n\n"
        "| Metric | Value |\n"
        "|---|---:|\n"
        f"{table}\n"
    )
