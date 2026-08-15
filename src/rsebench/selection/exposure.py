"""Explicit scanners for historical benchmark task exposure."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from rsebench.evidence import canonical_hash
from rsebench.selection.contracts import (
    ExposureLevel,
    ExposureRecord,
    ExposureRegistry,
    ExposureSource,
)


_SPLIT_FIELDS = {
    "train": "train",
    "train_task_ids": "train",
    "evolution": "evolution",
    "evolution_task_ids": "evolution",
    "validation": "validation",
    "validation_task_ids": "validation",
    "test": "test",
    "test_task_ids": "test",
    "clean_test": "clean_test",
    "clean_test_task_ids": "clean_test",
    "qualification_test": "qualification_test",
    "qualification_test_task_ids": "qualification_test",
    "screening_test": "screening_test",
    "screening_test_task_ids": "screening_test",
    "confirmation_test": "confirmation_test",
    "confirmation_test_task_ids": "confirmation_test",
}


def _string_id(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    task_id = str(value).strip()
    return task_id or None


def _split_item_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        task_id = _string_id(value.get("task_id"))
        if task_id is not None:
            return task_id
        goal_idx = _string_id(value.get("goal_idx"))
        if goal_idx is not None:
            return _goal_task_id(goal_idx)
        return None
    return _string_id(value)


def _goal_task_id(value: Any) -> str | None:
    goal_idx = _string_id(value)
    if goal_idx is None:
        return None
    return goal_idx if goal_idx.startswith("goal_") else f"goal_{goal_idx}"


def _find_benchmark(value: Any) -> str | None:
    if isinstance(value, Mapping):
        direct = _string_id(value.get("benchmark"))
        if direct is not None:
            return direct
        discovered = {
            benchmark
            for child in value.values()
            if (benchmark := _find_benchmark(child)) is not None
        }
        return next(iter(discovered)) if len(discovered) == 1 else None
    if isinstance(value, list):
        discovered = {
            benchmark
            for child in value
            if (benchmark := _find_benchmark(child)) is not None
        }
        return next(iter(discovered)) if len(discovered) == 1 else None
    return None


def _scan_payload(
    value: Any,
    *,
    inherited_benchmark: str | None = None,
) -> Iterator[tuple[str, str, str]]:
    if isinstance(value, list):
        for child in value:
            yield from _scan_payload(
                child,
                inherited_benchmark=inherited_benchmark,
            )
        return
    if not isinstance(value, Mapping):
        return

    benchmark = _string_id(value.get("benchmark")) or inherited_benchmark
    if benchmark is None:
        benchmark = _find_benchmark(value)

    for field, role in _SPLIT_FIELDS.items():
        rows = value.get(field)
        if benchmark is None or not isinstance(rows, list):
            continue
        for row in rows:
            task_id = _split_item_id(row)
            if task_id is not None:
                yield benchmark, task_id, role

    per_task_scores = value.get("per_task_scores")
    if benchmark is not None and isinstance(per_task_scores, Mapping):
        for raw_task_id in per_task_scores:
            task_id = _string_id(raw_task_id)
            if task_id is not None:
                yield benchmark, task_id, "per_task_scores"
    elif benchmark is not None and isinstance(per_task_scores, list):
        for row in per_task_scores:
            task_id = _split_item_id(row)
            if task_id is not None:
                yield benchmark, task_id, "per_task_scores"

    timing_rows = value.get("tasks")
    if benchmark is not None and isinstance(timing_rows, list):
        for row in timing_rows:
            if not isinstance(row, Mapping) or row.get("level") != "task":
                continue
            task_id = _string_id(row.get("task_id"))
            if task_id is not None:
                yield benchmark, task_id, "task_timing"

    instances = value.get("instances")
    if benchmark is not None and isinstance(instances, list):
        for row in instances:
            if isinstance(row, Mapping):
                task_id = next(
                    (
                        candidate
                        for field in ("task_id", "instance_id", "id")
                        if (candidate := _string_id(row.get(field))) is not None
                    ),
                    None,
                )
            else:
                task_id = _string_id(row)
            if task_id is not None:
                yield benchmark, task_id, "skilllearn_instance"

    instance_ids = value.get("instance_ids")
    if isinstance(instance_ids, list):
        for raw_task_id in instance_ids:
            task_id = _string_id(raw_task_id)
            if task_id is not None:
                yield benchmark or "skilllearnbench", task_id, "skilllearn_instance"

    goal_idx = _goal_task_id(value.get("goal_idx"))
    if goal_idx is not None:
        yield benchmark or "webshop", goal_idx, "goal_idx"

    for child in value.values():
        if isinstance(child, (Mapping, list)):
            yield from _scan_payload(child, inherited_benchmark=benchmark)


def _is_excluded(path: Path, excluded_roots: Sequence[Path]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == excluded or resolved.is_relative_to(excluded)
        for excluded in excluded_roots
    )


def _source_files(
    root: Path,
    *,
    excluded_roots: Sequence[Path] = (),
) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(f"exposure source does not exist: {root}")
    if root.is_file():
        return [] if _is_excluded(root, excluded_roots) else [root]
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".json", ".jsonl"}
        and not _is_excluded(path, excluded_roots)
    )


def _read_payloads(path: Path) -> Iterator[Any]:
    if path.suffix.lower() == ".jsonl":
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
        return
    try:
        yield json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}") from exc


def _artifact_level(
    source: ExposureSource,
    *,
    path: Path,
    role: str,
) -> ExposureLevel:
    """Cap planning-only artifacts without hiding real execution evidence."""

    if role == "per_task_scores":
        return ExposureLevel.score_observed
    if role == "task_timing":
        return ExposureLevel.executed
    planning_names = {
        "dry_run.json",
        "image_manifest.json",
        "image_manifest.verify.json",
        "image_record.json",
    }
    planning_parts = {"preflight", "dry-run"}
    if path.name in planning_names or planning_parts.intersection(path.parts):
        return ExposureLevel.manifest_only
    return source.level


def merge_record(
    current: ExposureRecord | None,
    *,
    benchmark: str,
    task_id: str,
    role: str,
    source: ExposureSource,
) -> ExposureRecord:
    """Merge one explicit task exposure while retaining maximum severity."""

    level = source.level
    if current is not None and current.level.rank > level.rank:
        level = current.level
    partition = _SPLIT_FIELDS.get(role)
    if current is not None and current.source_partition is not None:
        partition = current.source_partition
    first_experiment_id = current.first_experiment_id if current else None
    if first_experiment_id is None:
        first_experiment_id = source.experiment_id
    last_experiment_id = (
        source.experiment_id
        if source.experiment_id is not None
        else (current.last_experiment_id if current else None)
    )
    return ExposureRecord(
        benchmark=benchmark,
        task_id=task_id,
        source_partition=partition,
        level=level,
        roles=sorted(set((current.roles if current else []) + [role])),
        sources=sorted(set((current.sources if current else []) + [source.label])),
        first_experiment_id=first_experiment_id,
        last_experiment_id=last_experiment_id,
    )


def build_exposure_registry(
    sources: Sequence[ExposureSource],
    *,
    exclude_roots: Sequence[Path] = (),
) -> ExposureRegistry:
    """Scan only declared ID-bearing fields and merge by level precedence."""

    labels = [source.label for source in sources]
    if len(labels) != len(set(labels)):
        raise ValueError("exposure source labels must be unique")

    excluded = tuple(Path(path).resolve() for path in exclude_roots)
    merged: dict[tuple[str, str], ExposureRecord] = {}
    for source in sources:
        for path in _source_files(source.root, excluded_roots=excluded):
            for payload in _read_payloads(path):
                for benchmark, task_id, role in _scan_payload(payload):
                    effective_source = source.model_copy(
                        update={"level": _artifact_level(source, path=path, role=role)}
                    )
                    key = (benchmark, task_id)
                    merged[key] = merge_record(
                        merged.get(key),
                        benchmark=benchmark,
                        task_id=task_id,
                        role=role,
                        source=effective_source,
                    )

    records = [merged[key] for key in sorted(merged)]
    registry_hash = canonical_hash(
        [record.model_dump(mode="json") for record in records]
    )
    return ExposureRegistry(records=records, registry_hash=registry_hash)


__all__ = ["build_exposure_registry", "merge_record"]
