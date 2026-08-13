"""Human-readable reports for clean baseline qualification runs."""

from __future__ import annotations

from rsebench.evolution.clean_runner import CleanEvolutionResult


def _gate(passed: bool) -> str:
    return "passed" if passed else "failed"


def render_clean_report(result: CleanEvolutionResult) -> str:
    qualification = result.qualification
    audit = result.clean_artifact.execution_audit
    billed = result.token_usage["billed_tokens"]
    logical = result.token_usage["logical_tokens"]
    reasons = set(qualification.failure_reasons)
    rows = [
        ("Method", result.method),
        ("Method seed", str(result.method_seed)),
        ("Train tasks", str(len(audit.train_task_ids) if audit else 0)),
        ("Validation tasks", str(len(audit.validation_task_ids) if audit else 0)),
        ("Clean-test tasks", str(len(result.clean_evaluation.per_task_scores))),
        ("Seed score", f"{qualification.seed_score:.4f}"),
        ("Evolved score", f"{qualification.evolved_score:.4f}"),
        ("Clean gain", f"{qualification.clean_gain:+.4f}"),
        ("Execution coverage", _gate(qualification.execution_coverage_passed)),
        ("Artifact updated", "yes" if qualification.artifact_updated else "no"),
        ("Accepted updates", str(qualification.accepted_update_count)),
        ("Nondegrading", _gate(qualification.nondegrading)),
        (
            "Parseable-answer gate",
            _gate("parseable_answer_rate" not in reasons),
        ),
        (
            "Systemic-failure gate",
            _gate("systemic_failure_rate" not in reasons),
        ),
        ("Execution-failure gate", _gate("execution_failure" not in reasons)),
        ("Runtime gates", _gate(qualification.runtime_gates_passed)),
        ("Qualification", _gate(qualification.passed)),
        (
            "Failure reasons",
            ", ".join(qualification.failure_reasons) or "none",
        ),
        ("Billed tokens", str(billed["total_tokens"])),
        ("Logical tokens", str(logical["total_tokens"])),
        ("Token coverage", f"{result.token_usage['observed_coverage']:.4f}"),
    ]
    table = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return (
        "# Clean Baseline Qualification Result\n\n"
        "One clean evolution arm starts from the frozen seed skill and is "
        "evaluated on the untouched clean test split.\n\n"
        "| Metric | Value |\n"
        "|---|---:|\n"
        f"{table}\n"
    )
