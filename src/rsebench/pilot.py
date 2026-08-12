"""Deterministic split construction and immutable pilot run utilities."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SplitCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int = Field(gt=0)
    evolution: int = Field(ge=0)
    pilot_evolve: int = Field(ge=0)
    pilot_eval: int = Field(ge=0)
    validation: int = Field(ge=0)
    test: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_counts(self) -> "SplitCounts":
        if self.evolution + self.validation + self.test != self.total:
            raise ValueError("top-level split counts do not sum to total")
        if self.pilot_evolve + self.pilot_eval > self.evolution:
            raise ValueError("pilot split exceeds evolution partition")
        return self


class SplitManifest(BaseModel):
    benchmark: str
    seed: int
    evolution: list[str]
    pilot_evolve: list[str]
    pilot_eval: list[str]
    validation: list[str]
    test: list[str]
    group_assignments: dict[str, str]


def _order_key(seed: int, group_id: str) -> str:
    return hashlib.sha256(f"{seed}:{group_id}".encode("utf-8")).hexdigest()


def _select_exact_groups(
    groups: list[tuple[str, list[str]]], target: int, seed: int
) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
    ordered = sorted(groups, key=lambda row: _order_key(seed, row[0]))
    if target == 0:
        return [], ordered
    paths: dict[int, tuple[int, ...]] = {0: ()}
    for index, (_, ids) in enumerate(ordered):
        size = len(ids)
        for current, chosen in sorted(list(paths.items()), reverse=True):
            candidate = current + size
            if candidate <= target and candidate not in paths:
                paths[candidate] = (*chosen, index)
        if target in paths:
            break
    if target not in paths:
        sizes = sorted(len(ids) for _, ids in ordered)
        raise ValueError(f"cannot form exact task count {target} from group sizes {sizes}")
    selected_indices = set(paths[target])
    selected = [row for index, row in enumerate(ordered) if index in selected_indices]
    remaining = [row for index, row in enumerate(ordered) if index not in selected_indices]
    return selected, remaining


def _flatten(groups: list[tuple[str, list[str]]]) -> list[str]:
    return [task_id for _, ids in groups for task_id in sorted(ids)]


def build_split_manifest(
    *,
    benchmark: str,
    items: list[tuple[str, str]],
    counts: SplitCounts,
    seed: int,
) -> SplitManifest:
    if len(items) != counts.total or len({task_id for task_id, _ in items}) != counts.total:
        raise ValueError("items must contain exactly total unique task IDs")
    grouped: dict[str, list[str]] = defaultdict(list)
    for task_id, group_id in items:
        grouped[str(group_id)].append(str(task_id))
    groups = list(grouped.items())
    # Reserve the two nested pilot partitions before filling the remainder of
    # evolution. Selecting evolution first can choose an exact top-level count
    # whose group sizes make the requested nested pilot counts impossible.
    pilot_evolve_groups, remaining = _select_exact_groups(
        groups, counts.pilot_evolve, seed + 2
    )
    pilot_eval_groups, remaining = _select_exact_groups(
        remaining, counts.pilot_eval, seed + 3
    )
    evolution_extra_groups, remaining = _select_exact_groups(
        remaining,
        counts.evolution - counts.pilot_evolve - counts.pilot_eval,
        seed,
    )
    evolution_groups = [
        *pilot_evolve_groups,
        *pilot_eval_groups,
        *evolution_extra_groups,
    ]
    validation_groups, test_groups = _select_exact_groups(
        remaining, counts.validation, seed + 1
    )
    if len(_flatten(test_groups)) != counts.test:
        raise ValueError("test partition does not match requested count")
    assignments: dict[str, str] = {}
    for partition, partition_groups in (
        ("evolution", evolution_groups),
        ("validation", validation_groups),
        ("test", test_groups),
    ):
        for group_id, _ in partition_groups:
            assignments[group_id] = partition
    return SplitManifest(
        benchmark=benchmark,
        seed=seed,
        evolution=_flatten(evolution_groups),
        pilot_evolve=_flatten(pilot_evolve_groups),
        pilot_eval=_flatten(pilot_eval_groups),
        validation=_flatten(validation_groups),
        test=_flatten(test_groups),
        group_assignments=assignments,
    )


def create_run_directory(output_root: Path | str, kind: str, run_id: str) -> Path:
    path = Path(output_root) / "runs" / kind / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path
