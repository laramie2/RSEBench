"""Deterministic, secret-safe compact clean qualification releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from pydantic import Field

from rsebench.contracts import StrictModel
from rsebench.evidence import canonical_hash
from rsebench.experiments.bootstrap import BaselineFingerprint
from rsebench.experiments.preflight import ExperimentMatrix, FORMAL_METHOD_SEEDS
from rsebench.hashing import sha256_file


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{12,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
)
_CREDENTIAL_NAMES = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
)


class FrozenRelease(StrictModel):
    release_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: Path
    file_hashes: dict[str, str]


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _safe_result_path(run_root: Path, row: Mapping[str, Any]) -> tuple[Path, str]:
    locator = row.get("result_path") or row.get("path")
    if not isinstance(locator, str) or not locator.strip():
        raise ValueError("completed seed has no source result path")
    candidate = Path(locator)
    if not candidate.is_absolute():
        candidate = run_root / candidate
    if candidate.is_dir() or candidate.suffix != ".json":
        candidate /= "result.json"
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(run_root.resolve())
    except ValueError as exc:
        raise ValueError(f"source result escapes run root: {locator}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"source result is missing: {resolved}")
    return resolved, relative.as_posix()


def _numeric(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _timing_compact(result: Mapping[str, Any]) -> dict[str, Any]:
    timing = result.get("timing")
    if not isinstance(timing, dict) or not isinstance(timing.get("run"), dict):
        raise ValueError("source result lacks hierarchical timing")
    run = timing["run"]
    stages = timing.get("stages") or []
    tasks = timing.get("tasks") or []
    if not isinstance(stages, list) or not isinstance(tasks, list):
        raise ValueError("source result timing lists are malformed")
    stage_durations: dict[str, float] = {}
    stage_statuses: Counter[str] = Counter()
    for span in stages:
        if not isinstance(span, dict):
            raise ValueError("source stage timing is malformed")
        name = str(span.get("name") or "unknown")
        stage_durations[name] = stage_durations.get(name, 0.0) + _numeric(
            span.get("duration_seconds")
        )
        stage_statuses[str(span.get("status") or "unknown")] += 1
    task_statuses: Counter[str] = Counter()
    task_duration = 0.0
    for span in tasks:
        if not isinstance(span, dict):
            raise ValueError("source task timing is malformed")
        task_duration += _numeric(span.get("duration_seconds"))
        task_statuses[str(span.get("status") or "unknown")] += 1
    return {
        "run_duration_seconds": _numeric(run.get("duration_seconds")),
        "run_status": str(run.get("status") or "unknown"),
        "stage_duration_seconds": dict(sorted(stage_durations.items())),
        "stage_statuses": dict(sorted(stage_statuses.items())),
        "task_count": len(tasks),
        "task_duration_seconds": task_duration,
        "task_statuses": dict(sorted(task_statuses.items())),
    }


def _token_compact(result: Mapping[str, Any]) -> dict[str, Any]:
    token_usage = result.get("token_usage")
    if not isinstance(token_usage, dict):
        raise ValueError("source result lacks token usage summary")
    overall = token_usage.get("overall", token_usage)
    if not isinstance(overall, dict):
        raise ValueError("source token usage summary is malformed")
    fields = (
        "attempted_calls",
        "successful_calls",
        "failed_calls",
        "interrupted_calls",
        "observed_calls",
        "unobservable_calls",
        "cache_hit_calls",
    )
    compact: dict[str, Any] = {
        field: int(overall.get(field, 0) or 0) for field in fields
    }
    compact["observed_coverage"] = _numeric(overall.get("observed_coverage"), 1.0)
    for name in ("billed_tokens", "logical_tokens"):
        values = overall.get(name) or {}
        if not isinstance(values, dict):
            raise ValueError(f"source {name} summary is malformed")
        compact[name] = {
            field: int(values.get(field, 0) or 0)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
    return compact


def _sum_token_summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count_fields = (
        "attempted_calls",
        "successful_calls",
        "failed_calls",
        "interrupted_calls",
        "observed_calls",
        "unobservable_calls",
        "cache_hit_calls",
    )
    totals: dict[str, Any] = {
        field: sum(int(row[field]) for row in rows) for field in count_fields
    }
    attempted = totals["attempted_calls"]
    observed = totals["observed_calls"]
    if observed == 0 and attempted and all(
        "observed_calls" not in row or row["observed_calls"] == 0 for row in rows
    ):
        weighted = sum(
            row["observed_coverage"] * row["attempted_calls"] for row in rows
        )
        totals["observed_coverage"] = weighted / attempted
    else:
        totals["observed_coverage"] = observed / attempted if attempted else 1.0
    for name in ("billed_tokens", "logical_tokens"):
        totals[name] = {
            field: sum(int(row[name][field]) for row in rows)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
    return totals


def _contains_secret(files: Mapping[str, bytes]) -> tuple[str, str] | None:
    for name, content in files.items():
        text = content.decode("utf-8")
        for credential_name in _CREDENTIAL_NAMES:
            if credential_name in text:
                return name, credential_name
        for pattern in _SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                return name, match.group(0)[:12]
    return None


def _report_text(
    *,
    release_id: str,
    run_id: str,
    qualification: Mapping[str, Any],
    timing: Mapping[str, Any],
    tokens: Mapping[str, Any],
) -> str:
    lines = [
        "# Clean v2 baseline qualification release",
        "",
        f"- Release ID: `{release_id}`",
        f"- Run ID: `{run_id}`",
        f"- Cells: {len(qualification['cells'])}",
        f"- Formal seeds per cell: {len(FORMAL_METHOD_SEEDS)}",
        f"- Total run time: {timing['total_run_duration_seconds']:.6f} seconds",
        f"- Billed tokens: {tokens['overall']['billed_tokens']['total_tokens']}",
        "",
        "All configured cells are engineering-ready and efficacy-ready.",
        "",
    ]
    return "\n".join(lines)


def normalize_release_aggregate(
    aggregate: Mapping[str, Any],
    matrix: ExperimentMatrix,
) -> dict[str, Any]:
    """Project the legacy benchmark/family aggregate into configured cells."""

    if isinstance(aggregate.get("cells"), dict):
        return dict(aggregate)
    benchmarks = aggregate.get("benchmarks")
    skilllearn = aggregate.get("skilllearn")
    if not isinstance(benchmarks, dict) or not isinstance(skilllearn, dict):
        raise ValueError("aggregate cannot be mapped to configured release cells")
    families = skilllearn.get("families")
    cells: dict[str, Any] = {}
    for cell in matrix.cells:
        if cell.baseline.startswith("skilllearn"):
            if not isinstance(families, dict) or not cell.family:
                raise ValueError(f"SkillLearn release cell lacks a family: {cell.key}")
            readiness = families.get(cell.family)
        else:
            readiness = benchmarks.get(cell.benchmark)
        if not isinstance(readiness, dict):
            raise ValueError(f"aggregate lacks configured cell: {cell.key}")
        cells[cell.key] = readiness
    return {
        "schema_version": str(aggregate.get("schema_version") or "unknown"),
        "method_seeds": list(aggregate.get("method_seeds") or []),
        "cells": cells,
    }


def freeze_clean_release(
    *,
    run_root: Path | str,
    aggregate_path: Path | str | Mapping[str, Any],
    release_root: Path | str,
    run_id: str,
    baseline_fingerprints: Mapping[str, BaselineFingerprint],
) -> FrozenRelease:
    """Freeze one content-addressed clean release after all hard barriers pass."""

    source_root = Path(run_root).resolve()
    aggregate = (
        dict(aggregate_path)
        if isinstance(aggregate_path, Mapping)
        else _read_object(Path(aggregate_path))
    )
    if tuple(aggregate.get("method_seeds") or ()) != FORMAL_METHOD_SEEDS:
        raise ValueError("release requires the three fixed formal method seeds")
    cells = aggregate.get("cells")
    if not isinstance(cells, dict) or not cells:
        raise ValueError("aggregate has no configured release cells")
    if not baseline_fingerprints:
        raise ValueError("release requires baseline fingerprints")

    qualification_cells: dict[str, Any] = {}
    compact_cells: dict[str, Any] = {}
    timing_units: list[dict[str, Any]] = []
    token_units: list[dict[str, Any]] = []
    source_results: list[dict[str, Any]] = []
    for cell_key, cell_value in sorted(cells.items()):
        if not isinstance(cell_value, dict):
            raise ValueError(f"cell readiness is malformed: {cell_key}")
        if cell_value.get("efficacy_ready") is not True:
            raise ValueError(f"configured cell is not efficacy_ready: {cell_key}")
        if cell_value.get("engineering_ready") is not True:
            raise ValueError(f"configured cell is not engineering_ready: {cell_key}")
        expected = tuple(cell_value.get("expected_seeds") or ())
        seed_rows = cell_value.get("seed_results")
        if expected != FORMAL_METHOD_SEEDS or not isinstance(seed_rows, list):
            raise ValueError(f"cell does not declare exactly three formal seeds: {cell_key}")
        if len(seed_rows) != len(FORMAL_METHOD_SEEDS):
            raise ValueError(f"cell does not contain exactly three formal seeds: {cell_key}")
        by_seed = {int(row.get("method_seed", -1)): row for row in seed_rows}
        if tuple(sorted(by_seed)) != FORMAL_METHOD_SEEDS or len(by_seed) != len(seed_rows):
            raise ValueError(f"cell does not contain exactly three formal seeds: {cell_key}")

        compact_seeds: list[dict[str, Any]] = []
        for method_seed in FORMAL_METHOD_SEEDS:
            row = by_seed[method_seed]
            if row.get("status") != "completed":
                raise ValueError(f"source seed is not completed: {cell_key}/{method_seed}")
            result_path, relative = _safe_result_path(source_root, row)
            result = _read_object(result_path)
            experiment_id = str(row.get("experiment_id") or "")
            result_identity = result.get("identity")
            if (
                not re.fullmatch(r"[0-9a-f]{64}", experiment_id)
                or not isinstance(result_identity, dict)
                or result_identity.get("experiment_id") != experiment_id
                or int(result.get("method_seed", -1)) != method_seed
            ):
                raise ValueError(
                    f"source result identity does not match aggregate: {cell_key}/{method_seed}"
                )
            result_hash = sha256_file(result_path)
            source_results.append(
                {
                    "cell_key": cell_key,
                    "method_seed": method_seed,
                    "experiment_id": experiment_id,
                    "result_hash": result_hash,
                    "locator": f"rsebench-output://runs/{run_id}/{relative}",
                }
            )
            compact_seeds.append(
                {
                    "method_seed": method_seed,
                    "status": "completed",
                    "experiment_id": experiment_id,
                    "engineering_valid": bool(row.get("engineering_valid")),
                    "positive_gain": bool(row.get("positive_gain")),
                    "clean_gain": _numeric(row.get("clean_gain")),
                    "result_hash": result_hash,
                }
            )
            timing_units.append(
                {
                    "cell_key": cell_key,
                    "method_seed": method_seed,
                    **_timing_compact(result),
                }
            )
            token_units.append(
                {
                    "cell_key": cell_key,
                    "method_seed": method_seed,
                    **_token_compact(result),
                }
            )
        readiness = {
            key: cell_value.get(key)
            for key in (
                "expected_seeds",
                "engineering_valid_seeds",
                "positive_gain_seeds",
                "engineering_ready",
                "efficacy_ready",
                "failure_reasons",
            )
        }
        qualification_cells[cell_key] = readiness
        compact_cells[cell_key] = {**readiness, "seed_results": compact_seeds}

    qualification = {
        "schema_version": "rsebench.clean-release-qualification.v1",
        "all_cells_engineering_ready": True,
        "all_cells_efficacy_ready": True,
        "cells": qualification_cells,
    }
    compact_aggregate = {
        "schema_version": str(aggregate.get("schema_version") or "unknown"),
        "method_seeds": list(FORMAL_METHOD_SEEDS),
        "cells": compact_cells,
    }
    timing_summary = {
        "schema_version": "rsebench.clean-release-timing.v1",
        "total_run_duration_seconds": sum(
            row["run_duration_seconds"] for row in timing_units
        ),
        "total_task_duration_seconds": sum(
            row["task_duration_seconds"] for row in timing_units
        ),
        "total_task_count": sum(row["task_count"] for row in timing_units),
        "units": timing_units,
    }
    token_summary = {
        "schema_version": "rsebench.clean-release-token.v1",
        "overall": _sum_token_summaries(token_units),
        "units": token_units,
    }
    baseline_payload = {
        name: fingerprint.model_dump(mode="json")
        for name, fingerprint in sorted(baseline_fingerprints.items())
    }
    core = {
        "schema_version": "rsebench.clean-release-content.v1",
        "run_id": run_id,
        "baseline_fingerprints": baseline_payload,
        "source_results": source_results,
        "qualification": qualification,
        "aggregate": compact_aggregate,
        "timing_summary": timing_summary,
        "token_summary": token_summary,
    }
    release_id = canonical_hash(core)
    files: dict[str, bytes] = {
        "qualification.json": _json_bytes(qualification),
        "aggregate.json": _json_bytes(compact_aggregate),
        "timing-summary.json": _json_bytes(timing_summary),
        "token-summary.json": _json_bytes(token_summary),
        "report.md": _report_text(
            release_id=release_id,
            run_id=run_id,
            qualification=qualification,
            timing=timing_summary,
            tokens=token_summary,
        ).encode("utf-8"),
    }
    artifact_hashes = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted(files.items())
    }
    manifest = {
        "schema_version": "rsebench.clean-release.v1",
        "release_id": release_id,
        "track": "clean-v2",
        "formal_qualification": True,
        "run_id": run_id,
        "baseline_fingerprints": baseline_payload,
        "source_results": source_results,
        "artifact_hashes": artifact_hashes,
    }
    files["manifest.json"] = _json_bytes(manifest)
    secret = _contains_secret(files)
    if secret is not None:
        name, match = secret
        raise ValueError(
            f"secret-like content detected before release write: {name} ({match})"
        )

    destination_root = Path(release_root).resolve()
    destination = destination_root / release_id
    if destination.exists():
        actual = {
            path.relative_to(destination).as_posix(): path.read_bytes()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if actual != files:
            raise RuntimeError(f"existing release content differs: {destination}")
        return FrozenRelease(
            release_id=release_id,
            path=destination,
            file_hashes={
                name: hashlib.sha256(content).hexdigest()
                for name, content in sorted(files.items())
            },
        )

    destination_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".freeze-", dir=destination_root))
    try:
        for name, content in files.items():
            (temporary / name).write_bytes(content)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return FrozenRelease(
        release_id=release_id,
        path=destination,
        file_hashes={
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(files.items())
        },
    )


__all__ = [
    "FrozenRelease",
    "freeze_clean_release",
    "normalize_release_aggregate",
]
