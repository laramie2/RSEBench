#!/usr/bin/env python3
"""Aggregate fixed-denominator clean baseline qualification outcomes."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.experiments.qualification import (  # noqa: E402
    SeedReadiness,
    aggregate_cell_readiness,
)
from rsebench.experiments.preflight import ExperimentMatrix  # noqa: E402
from rsebench.hashing import sha256_file  # noqa: E402
from rsebench.usage import aggregate_token_usage_tree  # noqa: E402


METHOD_SEEDS = (20260813, 20260814, 20260815)
BENCHMARKS = (
    "spreadsheetbench_verified",
    "officeqa_full",
    "webshop",
)
SKILLLEARN_FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
    "github-repo-analytics",
    "financial-analysis",
    "stock-data-visualization",
    "enterprise-information-search",
)
SCHEMA_VERSION = "rsebench.clean-qualification-aggregate.v2"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _split_metadata(result_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    split_path = result_path.parent / "split_manifest.json"
    if not split_path.is_file():
        return {}, {}
    split = _read_json(split_path)
    metadata = split.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return split, metadata


def _config_version(result_path: Path, result: dict[str, Any]) -> str:
    metadata = result.get("metadata", {})
    if isinstance(metadata, dict) and metadata.get("config_version"):
        return str(metadata["config_version"])
    _, split_metadata = _split_metadata(result_path)
    return str(split_metadata.get("config_version", "unknown"))


def _validate_identity(
    *,
    result_path: Path,
    result: dict[str, Any],
    benchmark: str,
    family: str | None,
    method_seed: int,
) -> None:
    if int(result.get("method_seed", -1)) != method_seed:
        raise ValueError(f"method seed mismatch: {result_path}")
    split, split_metadata = _split_metadata(result_path)
    declared_benchmark = result.get("benchmark") or split.get("benchmark")
    if declared_benchmark is not None and declared_benchmark != benchmark:
        raise ValueError(f"benchmark mismatch: {result_path}")
    declared_family = (
        result.get("family")
        or split_metadata.get("family")
        or split_metadata.get("task_family")
    )
    if family is not None and declared_family is not None and declared_family != family:
        raise ValueError(f"SkillLearn family mismatch: {result_path}")
    identity = result.get("identity")
    if not isinstance(identity, dict):
        raise ValueError(f"result lacks v2 experiment identity: {result_path}")
    experiment_id = identity.get("experiment_id")
    inputs = identity.get("inputs")
    if (
        not isinstance(experiment_id, str)
        or len(experiment_id) != 64
        or any(character not in "0123456789abcdef" for character in experiment_id)
        or not isinstance(inputs, dict)
    ):
        raise ValueError(f"result has malformed v2 experiment identity: {result_path}")
    if canonical_hash(inputs) != experiment_id:
        raise ValueError(f"result experiment identity hash mismatch: {result_path}")
    if int(inputs.get("method_seed", -1)) != method_seed:
        raise ValueError(f"identity method seed mismatch: {result_path}")
    identity_benchmark = inputs.get("benchmark")
    if identity_benchmark is not None and identity_benchmark != benchmark:
        raise ValueError(f"identity benchmark mismatch: {result_path}")


def _identity_family(result: dict[str, Any]) -> tuple[str, str]:
    identity = result["identity"]
    inputs = dict(identity["inputs"])
    inputs.pop("method_seed", None)
    return str(identity["experiment_id"]), canonical_hash(inputs)


def _result_paths(seed_dir: Path) -> list[Path]:
    return sorted(seed_dir.glob("*/result.json"))


def _collect_seed(
    run_root: Path,
    *,
    benchmark: str,
    method_seed: int,
    family: str | None = None,
) -> dict[str, Any]:
    seed_dir = run_root / benchmark
    if family is not None:
        seed_dir /= family
    seed_dir /= str(method_seed)
    result_paths = _result_paths(seed_dir)
    if not result_paths:
        return SeedReadiness(
            method_seed=method_seed,
            status="missing",
            failure_reasons=["missing_seed"],
        ).model_dump(mode="json")

    loaded = [(path, _read_json(path)) for path in result_paths]
    by_config: dict[str, list[Path]] = {}
    for path, result in loaded:
        by_config.setdefault(_config_version(path, result), []).append(path)
    duplicate = next((paths for paths in by_config.values() if len(paths) > 1), None)
    if duplicate is not None:
        raise ValueError(
            "duplicate completed clean qualification for "
            f"{benchmark}/{family or '-'}/{method_seed}: "
            + ", ".join(str(path) for path in duplicate)
        )
    if len(loaded) > 1:
        raise ValueError(
            "multiple clean qualification config versions are ambiguous for "
            f"{benchmark}/{family or '-'}/{method_seed}"
        )

    result_path, result = loaded[0]
    return _completed_seed(
        result_path=result_path,
        result=result,
        benchmark=benchmark,
        family=family,
        method_seed=method_seed,
        run_root=run_root,
    )


def _completed_seed(
    *,
    result_path: Path,
    result: dict[str, Any],
    benchmark: str,
    family: str | None,
    method_seed: int,
    run_root: Path,
) -> dict[str, Any]:
    _validate_identity(
        result_path=result_path,
        result=result,
        benchmark=benchmark,
        family=family,
        method_seed=method_seed,
    )
    qualification = result.get("qualification")
    if not isinstance(qualification, dict) or not isinstance(
        qualification.get("passed"), bool
    ):
        raise ValueError(f"result lacks typed qualification: {result_path}")
    experiment_id, identity_family_hash = _identity_family(result)
    clean_gain = float(qualification.get("clean_gain", 0.0))
    engineering_valid = bool(qualification["passed"])
    return SeedReadiness(
        method_seed=method_seed,
        status="completed",
        identity_family_hash=identity_family_hash,
        experiment_id=experiment_id,
        engineering_valid=engineering_valid,
        clean_gain=clean_gain,
        positive_gain=engineering_valid and clean_gain > 0.0,
        accepted_update_count=int(qualification.get("accepted_update_count", 0)),
        seed_score=float(qualification.get("seed_score", 0.0)),
        evolved_score=float(qualification.get("evolved_score", 0.0)),
        failure_reasons=list(qualification.get("failure_reasons", [])),
        run_id=result_path.parent.name,
        path=result_path.parent.relative_to(run_root).as_posix(),
        config_version=_config_version(result_path, result),
    ).model_dump(mode="json")


def _summarize_runs(
    runs: list[dict[str, Any]],
    *,
    expected_seeds: tuple[int, ...] = METHOD_SEEDS,
) -> dict[str, Any]:
    statuses = Counter(str(run["status"]) for run in runs)
    readiness = aggregate_cell_readiness(
        [SeedReadiness.model_validate(run) for run in runs],
        expected_seeds=expected_seeds,
    ).model_dump(mode="json")
    return {
        **readiness,
        "total_runs": len(expected_seeds),
        "required_engineering_valid_runs": 2,
        "required_positive_gain_runs": 2,
        "passed_runs": len(readiness["engineering_valid_seeds"]),
        "missing_runs": statuses.get("missing", 0),
        "statuses": dict(sorted(statuses.items())),
        "qualified": readiness["efficacy_ready"],
        "deprecated_fields": {
            "passed_runs": "alias count for engineering_valid_seeds",
            "qualified": "deprecated alias of efficacy_ready",
        },
    }


def _scheduler_status(run_root: Path) -> dict[str, Any]:
    path = run_root / "matrix_status.json"
    if not path.is_file():
        return {"metadata": {}, "units": {}}
    payload = _read_json(path)
    if not isinstance(payload.get("units"), dict):
        raise ValueError(f"scheduler status has malformed units: {path}")
    return payload


def _scheduler_result_path(
    run_root: Path,
    *,
    unit_key: str,
    row: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    attempts = row.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError(f"completed scheduler unit has no attempts: {unit_key}")
    attempt = attempts[-1]
    if not isinstance(attempt, dict):
        raise ValueError(f"scheduler attempt is malformed: {unit_key}")
    locator = attempt.get("result_path")
    if not isinstance(locator, str) or not locator.strip():
        raise ValueError(f"completed scheduler unit has no result path: {unit_key}")
    candidate = Path(locator)
    if not candidate.is_absolute():
        candidate = run_root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(run_root.resolve())
    except ValueError as exc:
        raise ValueError(f"scheduler result escapes run root: {unit_key}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"scheduler result is missing: {resolved}")
    expected_hash = attempt.get("result_hash")
    if expected_hash is not None and sha256_file(resolved) != expected_hash:
        raise ValueError(f"scheduler result hash mismatch: {unit_key}")
    return resolved, attempt


def _collect_scheduled_seed(
    run_root: Path,
    *,
    status: dict[str, Any],
    unit_key: str,
    benchmark: str,
    family: str | None,
    method_seed: int,
) -> dict[str, Any]:
    row = status["units"].get(unit_key)
    if not isinstance(row, dict):
        return SeedReadiness(
            method_seed=method_seed,
            status="missing",
            failure_reasons=["missing_seed"],
        ).model_dump(mode="json")
    state = str(row.get("state") or "invalid")
    if state != "completed":
        mapped_state = state if state in {"failed", "interrupted", "invalid"} else "invalid"
        return SeedReadiness(
            method_seed=method_seed,
            status=mapped_state,
            failure_reasons=[f"scheduler_{state}"],
        ).model_dump(mode="json")
    result_path, attempt = _scheduler_result_path(
        run_root,
        unit_key=unit_key,
        row=row,
    )
    result = _read_json(result_path)
    result_identity = result.get("identity")
    result_experiment_id = (
        result_identity.get("experiment_id")
        if isinstance(result_identity, dict)
        else None
    )
    if result_experiment_id != row.get("experiment_id"):
        raise ValueError(
            f"scheduler/result experiment identity mismatch: {unit_key}"
        )
    seed = _completed_seed(
        result_path=result_path,
        result=result,
        benchmark=benchmark,
        family=family,
        method_seed=method_seed,
        run_root=run_root,
    )
    seed["run_id"] = str(attempt.get("attempt_id") or result_path.parent.name)
    seed["path"] = result_path.relative_to(run_root.resolve()).as_posix()
    return seed


def _build_matrix_aggregate(
    run_root: Path,
    matrix: ExperimentMatrix,
) -> dict[str, Any]:
    status = _scheduler_status(run_root)
    expected_seeds = tuple(matrix.method_seeds)
    expected_unit_count = len(matrix.cells) * len(expected_seeds)
    declared_count = status.get("metadata", {}).get("expected_units")
    if declared_count is not None and int(declared_count) != expected_unit_count:
        raise ValueError("scheduler expected unit count differs from matrix")
    cells: dict[str, Any] = {}
    for cell in matrix.cells:
        runs = [
            _collect_scheduled_seed(
                run_root,
                status=status,
                unit_key=f"{cell.key}:{method_seed}",
                benchmark=cell.benchmark,
                family=cell.family,
                method_seed=method_seed,
            )
            for method_seed in expected_seeds
        ]
        cells[cell.key] = _summarize_runs(
            runs,
            expected_seeds=expected_seeds,
        )
    all_engineering_ready = all(
        bool(cell["engineering_ready"]) for cell in cells.values()
    )
    all_efficacy_ready = all(bool(cell["efficacy_ready"]) for cell in cells.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "run_root": str(run_root),
        "method_seeds": list(expected_seeds),
        "cells": cells,
        "all_cells_engineering_ready": all_engineering_ready,
        "all_cells_efficacy_ready": all_efficacy_ready,
        "all_benchmarks_engineering_ready": all_engineering_ready,
        "all_benchmarks_efficacy_ready": all_efficacy_ready,
        "all_benchmarks_qualified": all_efficacy_ready,
        "deprecated_fields": {
            "all_benchmarks_qualified": (
                "deprecated alias of all_cells_efficacy_ready"
            )
        },
        "token_usage": aggregate_token_usage_tree(run_root),
    }


def build_aggregate(
    run_root: Path,
    *,
    matrix: ExperimentMatrix | None = None,
) -> dict[str, Any]:
    """Build the sole formal barrier decision for starting N1 experiments."""

    run_root = Path(run_root)
    if matrix is not None:
        return _build_matrix_aggregate(run_root, matrix)
    benchmarks: dict[str, Any] = {}
    for benchmark in BENCHMARKS:
        runs = [
            _collect_seed(
                run_root,
                benchmark=benchmark,
                method_seed=method_seed,
            )
            for method_seed in METHOD_SEEDS
        ]
        benchmarks[benchmark] = _summarize_runs(runs)

    family_results: dict[str, Any] = {}
    for family in SKILLLEARN_FAMILIES:
        runs = [
            _collect_seed(
                run_root,
                benchmark="skilllearnbench",
                family=family,
                method_seed=method_seed,
            )
            for method_seed in METHOD_SEEDS
        ]
        family_results[family] = _summarize_runs(runs)
    engineering_ready_family_count = sum(
        bool(result["engineering_ready"]) for result in family_results.values()
    )
    efficacy_ready_family_count = sum(
        bool(result["efficacy_ready"]) for result in family_results.values()
    )
    skilllearn = {
        "families": family_results,
        "total_families": len(SKILLLEARN_FAMILIES),
        "required_ready_families": 4,
        "engineering_ready_family_count": engineering_ready_family_count,
        "efficacy_ready_family_count": efficacy_ready_family_count,
        "engineering_ready": engineering_ready_family_count >= 4,
        "efficacy_ready": efficacy_ready_family_count >= 4,
        "qualified": efficacy_ready_family_count >= 4,
        "deprecated_fields": {"qualified": "deprecated alias of efficacy_ready"},
    }
    all_benchmarks_engineering_ready = all(
        result["engineering_ready"] for result in benchmarks.values()
    ) and bool(skilllearn["engineering_ready"])
    all_benchmarks_efficacy_ready = all(
        result["efficacy_ready"] for result in benchmarks.values()
    ) and bool(skilllearn["efficacy_ready"])
    return {
        "schema_version": SCHEMA_VERSION,
        "run_root": str(run_root),
        "method_seeds": list(METHOD_SEEDS),
        "benchmarks": benchmarks,
        "skilllearn": skilllearn,
        "all_benchmarks_engineering_ready": all_benchmarks_engineering_ready,
        "all_benchmarks_efficacy_ready": all_benchmarks_efficacy_ready,
        "all_benchmarks_qualified": all_benchmarks_efficacy_ready,
        "deprecated_fields": {
            "all_benchmarks_qualified": (
                "deprecated alias of all_benchmarks_efficacy_ready"
            )
        },
        "token_usage": aggregate_token_usage_tree(run_root),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_aggregate(args.run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
