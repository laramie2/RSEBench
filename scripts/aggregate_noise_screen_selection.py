#!/usr/bin/env python3
"""Aggregate clean qualification and fixed-artifact replay evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = PROJECT_ROOT / "src"
for source in reversed((PROJECT_SRC, PROJECT_ROOT)):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from rsebench.selection.contracts import (  # noqa: E402
    CandidateSeedEvidence,
    DomainSelectionStatus,
    SelectionStatus,
)
from rsebench.selection.qualification import (  # noqa: E402
    decide_candidate,
    replay_action,
    replay_integrity_failures,
    reuse_action,
    sequential_incomplete_action,
)


POOL_BENCHMARKS = (
    "spreadsheetbench_verified",
    "officeqa_full",
    "webshop",
)
SKILLLEARN_FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
)


def replay_decision_action(replay: Mapping[str, Any]) -> str:
    """Derive the 3-to-5 branch only from the persisted clean replay summary."""

    summaries = replay.get("summaries")
    clean = summaries.get("clean") if isinstance(summaries, Mapping) else None
    deltas = clean.get("deltas_vs_reference") if isinstance(clean, Mapping) else None
    if not isinstance(deltas, list) or not deltas:
        raise ValueError("clean replay summary lacks paired deltas")
    return replay_action(
        [float(value) for value in deltas],
        repeats=int(replay.get("repeat_count", 0)),
    )


def _applicability_rows(candidate_audit: Mapping[str, Any]) -> Mapping[str, Any]:
    static_gates = candidate_audit.get("static_gates")
    if isinstance(static_gates, Mapping):
        rows = static_gates.get("noise_applicability")
        if isinstance(rows, Mapping):
            return rows
    rows = candidate_audit.get("noise_applicability")
    return rows if isinstance(rows, Mapping) else {}


def merged_audit_failures(
    *,
    candidate_audit: Mapping[str, Any],
    trace_audit: Mapping[str, Any],
) -> list[str]:
    """Merge provider-free N1/N2 gates with actual N3/N4 trace gates."""

    static_rows = _applicability_rows(candidate_audit)
    failures: list[str] = []
    for stage in ("N1", "N2", "N3", "N4"):
        raw = (
            trace_audit.get(stage) if stage in {"N3", "N4"} else static_rows.get(stage)
        )
        if raw is None and stage in {"N3", "N4"}:
            raw = static_rows.get(stage)
        if not isinstance(raw, Mapping):
            failures.append(f"missing_noise_applicability:{stage}")
            continue
        status = raw.get("status")
        coverage = raw.get("coverage")
        if status == "pending":
            failures.append(f"pending_noise_applicability:{stage}")
        elif status != "pass" or coverage != 1.0:
            failures.append(f"incomplete_noise_applicability:{stage}")
    return failures


def _execution_coverage(row: Mapping[str, Any]) -> tuple[float, list[str]]:
    expected = row.get("expected_task_ids")
    executed = row.get("executed_task_ids")
    if not isinstance(expected, list) or not expected:
        return 0.0, ["missing_expected_task_denominator"]
    if len(expected) != len(set(expected)):
        return 0.0, ["duplicate_expected_task_id"]
    if not isinstance(executed, list):
        return 0.0, ["missing_executed_task_ids"]
    reasons: list[str] = []
    if len(executed) != len(set(executed)):
        reasons.append("duplicate_executed_task_id")
    expected_set = set(expected)
    executed_set = set(executed)
    if not executed_set.issubset(expected_set):
        reasons.append("unexpected_executed_task_id")
    coverage = len(expected_set & executed_set) / len(expected_set)
    if coverage != 1.0:
        reasons.append("incomplete_execution_coverage")
    return coverage, reasons


def _selection_audit_failures(row: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    candidate_audit = row.get("candidate_audit")
    trace_audit = row.get("trace_audit")
    if not isinstance(candidate_audit, Mapping) or not isinstance(trace_audit, Mapping):
        failures.append("missing_candidate_or_trace_audit")
    else:
        failures.extend(
            merged_audit_failures(
                candidate_audit=candidate_audit,
                trace_audit=trace_audit,
            )
        )
    domain_audit = row.get("domain_audit")
    if not isinstance(domain_audit, Mapping):
        failures.append("missing_domain_audit")
    elif domain_audit.get("passed") is not True:
        reasons = domain_audit.get("failure_reasons")
        if isinstance(reasons, list) and reasons:
            failures.extend(str(reason) for reason in reasons)
        else:
            failures.append("domain_structural_audit_failed")
    _, coverage_failures = _execution_coverage(row)
    failures.extend(coverage_failures)
    return failures


def _pool_integrity_failures(row: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    replays = row.get("replays")
    if not isinstance(replays, list) or len(replays) != 3:
        failures.append("missing_fixed_three_seed_replays")
    else:
        for replay in replays:
            if not isinstance(replay, Mapping):
                failures.append("malformed_replay_result")
                continue
            failures.extend(replay_integrity_failures(replay))
    reuse_checks = row.get("reuse_checks")
    if not isinstance(reuse_checks, list) or len(reuse_checks) != 3:
        failures.append("missing_reuse_identity")
    else:
        seen_seeds: set[int] = set()
        invariant_values: dict[str, set[Any]] = {
            field: set()
            for field in (
                "baseline_fingerprint",
                "evolution_input_hash",
                "provider",
                "model",
                "provider_config_hash",
            )
        }
        for index, check in enumerate(reuse_checks):
            if not isinstance(check, Mapping):
                failures.append("missing_reuse_identity")
                continue
            actual = check.get("actual")
            expected = check.get("expected")
            if not isinstance(actual, Mapping) or not isinstance(expected, Mapping):
                failures.append("missing_reuse_identity")
                continue
            if reuse_action(actual, expected) != "reuse_artifact":
                failures.append("reuse_identity_mismatch")
                continue
            method_seed = actual.get("method_seed")
            if isinstance(method_seed, bool) or not isinstance(method_seed, int):
                failures.append("missing_reuse_method_seed")
            elif method_seed in seen_seeds:
                failures.append("duplicate_reuse_method_seed")
            else:
                seen_seeds.add(method_seed)
            for field, values in invariant_values.items():
                values.add(actual.get(field))
            if isinstance(replays, list) and index < len(replays):
                hashes = replays[index].get("artifact_hashes")
                if (
                    not isinstance(hashes, Mapping)
                    or actual.get("artifact_hash") not in hashes.values()
                ):
                    failures.append("replay_artifact_hash_mismatch")
        if len(invariant_values["baseline_fingerprint"]) > 1:
            failures.append("mixed_reuse_fingerprints")
        if any(
            len(values) > 1
            for field, values in invariant_values.items()
            if field != "baseline_fingerprint"
        ):
            failures.append("mixed_reuse_identity")
        seeds_raw = row.get("seeds")
        if isinstance(seeds_raw, list):
            evidence_seeds = {
                seed.get("method_seed")
                for seed in seeds_raw
                if isinstance(seed, Mapping)
            }
            if seen_seeds != evidence_seeds:
                failures.append("reuse_method_seed_mismatch")
    failures.extend(_selection_audit_failures(row))
    return list(dict.fromkeys(failures))


def _pool_status(benchmark: str, row: Mapping[str, Any]) -> DomainSelectionStatus:
    candidate_index = int(row.get("candidate_index", 0))
    failures = _pool_integrity_failures(row)
    if failures:
        return DomainSelectionStatus(
            benchmark=benchmark,
            next_action=sequential_incomplete_action(candidate_index),
            reasons=failures,
        )
    replays = row.get("replays")
    if isinstance(replays, list):
        if any(
            replay_decision_action(replay) == "extend_replay_to_5"
            for replay in replays
            if isinstance(replay, Mapping)
        ):
            return DomainSelectionStatus(
                benchmark=benchmark,
                next_action="extend_replay_to_5",
                reasons=["sign_inconsistent_three_repeat_replay"],
            )
    seeds_raw = row.get("seeds")
    if not isinstance(seeds_raw, list):
        raise ValueError(f"candidate seed evidence is missing: {benchmark}")
    seeds = [CandidateSeedEvidence.model_validate(seed) for seed in seeds_raw]
    execution_coverage, _ = _execution_coverage(row)
    decision = decide_candidate(
        candidate_index=candidate_index,
        seeds=seeds,
        execution_coverage=execution_coverage,
        noise_applicability=1.0,
    )
    return DomainSelectionStatus(
        benchmark=benchmark,
        selected_candidate_index=(candidate_index if decision.passed else None),
        next_action=decision.next_action,
        reasons=decision.failure_reasons,
    )


def _family_ready(row: Mapping[str, Any]) -> bool:
    seeds = row.get("seeds")
    if not isinstance(seeds, list) or len(seeds) != 3:
        return False
    method_seeds: set[int] = set()
    ready = 0
    for seed in seeds:
        if not isinstance(seed, Mapping):
            return False
        method_seed = seed.get("method_seed")
        if isinstance(method_seed, bool) or not isinstance(method_seed, int):
            return False
        method_seeds.add(method_seed)
        check = seed.get("reuse_check")
        if not isinstance(check, Mapping):
            return False
        actual = check.get("actual")
        expected = check.get("expected")
        if (
            not isinstance(actual, Mapping)
            or not isinstance(expected, Mapping)
            or reuse_action(actual, expected) != "reuse_artifact"
            or actual.get("method_seed") != method_seed
        ):
            return False
        if (
            int(seed.get("accepted_update_count", 0)) > 0
            and seed.get("artifact_changed") is True
            and seed.get("validation_complete") is True
        ):
            ready += 1
    return len(method_seeds) == 3 and ready >= 2


def _skilllearn_status(row: Mapping[str, Any]) -> DomainSelectionStatus:
    families = row.get("families")
    if not isinstance(families, Mapping) or set(families) != set(SKILLLEARN_FAMILIES):
        raise ValueError("SkillLearn aggregation requires exactly four fixed families")
    audit_failures = _selection_audit_failures(row)
    if audit_failures:
        return DomainSelectionStatus(
            benchmark="skilllearnbench",
            next_action="clean_blocked_skilllearn_families",
            reasons=audit_failures,
        )
    ready = [
        family
        for family in SKILLLEARN_FAMILIES
        if isinstance(families[family], Mapping) and _family_ready(families[family])
    ]
    if len(ready) >= 3:
        return DomainSelectionStatus(
            benchmark="skilllearnbench",
            selected_candidate_index=1,
            next_action="freeze_candidate",
            reasons=[],
        )
    return DomainSelectionStatus(
        benchmark="skilllearnbench",
        next_action="clean_blocked_skilllearn_families",
        reasons=[
            "fewer_than_three_clean_ready_skilllearn_families",
            *[
                f"family_not_ready:{family}"
                for family in SKILLLEARN_FAMILIES
                if family not in ready
            ],
        ],
    )


def build_selection_status(payload: Mapping[str, Any]) -> SelectionStatus:
    """Build the sequential-stopping control file for the next clean action."""

    domains = payload.get("domains")
    if not isinstance(domains, Mapping) or set(domains) != set(POOL_BENCHMARKS):
        raise ValueError("selection aggregate requires exactly three pool domains")
    skilllearn = payload.get("skilllearn")
    if not isinstance(skilllearn, Mapping):
        raise ValueError("selection aggregate requires SkillLearn evidence")
    statuses = {
        benchmark: _pool_status(benchmark, domains[benchmark])
        for benchmark in POOL_BENCHMARKS
    }
    statuses["skilllearnbench"] = _skilllearn_status(skilllearn)
    return SelectionStatus(domains=statuses)


def aggregate_from_roots(
    *,
    selection_root: Path,
    run_root: Path,
    mode: str,
    clean_v2_root: Path | None = None,
    skillopt_replay_root: Path | None = None,
) -> Any:
    from rsebench.selection.qualification_io import aggregate_selection_roots

    return aggregate_selection_roots(
        selection_root=selection_root,
        run_root=run_root,
        mode=mode,
        clean_v2_root=clean_v2_root,
        skillopt_replay_root=skillopt_replay_root,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--selection-root", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--clean-v2-root", type=Path)
    parser.add_argument("--skillopt-replay-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("reuse-audit", "qualification", "screening-generalization"),
        default="qualification",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.input is not None:
        if args.selection_root is not None or args.run_root is not None:
            raise ValueError("--input cannot be combined with root aggregation")
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("selection aggregate input must be an object")
        output_payload: Any = build_selection_status(payload)
    else:
        if args.selection_root is None:
            raise ValueError("root mode requires --selection-root")
        run_root = args.run_root or args.output.parent
        if args.mode != "reuse-audit" and args.run_root is None:
            raise ValueError(f"{args.mode} mode requires --run-root")
        output_payload = aggregate_from_roots(
            selection_root=args.selection_root,
            run_root=run_root,
            mode=args.mode,
            clean_v2_root=args.clean_v2_root,
            skillopt_replay_root=args.skillopt_replay_root,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(output_payload, "model_dump_json"):
        encoded = output_payload.model_dump_json(indent=2) + "\n"
    else:
        encoded = (
            json.dumps(output_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
    args.output.write_text(encoded, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
