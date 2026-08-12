"""Deterministic, leakage-resistant split construction."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from pydantic import model_validator

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evolution.contracts import EvolutionSplitManifest, EvolutionTaskPair


class BaseTaskSplit(StrictModel):
    train: list[TaskManifest]
    validation: list[TaskManifest]
    clean_test: list[TaskManifest]

    @model_validator(mode="after")
    def disjoint_ids(self) -> "BaseTaskSplit":
        ids = [
            task.task_id
            for group in (self.train, self.validation, self.clean_test)
            for task in group
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("split task IDs must be disjoint")
        return self


def _group_rank(seed: int, group_id: str) -> str:
    return hashlib.sha256(f"{seed}:{group_id}".encode()).hexdigest()


def deterministic_group_split(
    tasks: list[TaskManifest],
    *,
    seed: int,
    train_groups: int,
    validation_groups: int,
    test_groups: int,
    group_key: str = "group_id",
) -> BaseTaskSplit:
    requested = train_groups + validation_groups + test_groups
    grouped: dict[str, list[TaskManifest]] = defaultdict(list)
    for task in tasks:
        group_id = str(task.metadata.get(group_key) or task.task_id)
        grouped[group_id].append(task)
    if requested > len(grouped):
        raise ValueError(
            f"insufficient groups: requested {requested}, available {len(grouped)}"
        )
    ordered_groups = sorted(grouped, key=lambda value: (_group_rank(seed, value), value))
    train_ids = set(ordered_groups[:train_groups])
    validation_ids = set(
        ordered_groups[train_groups : train_groups + validation_groups]
    )
    test_ids = set(
        ordered_groups[
            train_groups + validation_groups : requested
        ]
    )

    def collect(group_ids: set[str]) -> list[TaskManifest]:
        return sorted(
            [task for gid in group_ids for task in grouped[gid]],
            key=lambda task: task.task_id,
        )

    return BaseTaskSplit(
        train=collect(train_ids),
        validation=collect(validation_ids),
        clean_test=collect(test_ids),
    )


def build_evolution_split(
    *,
    benchmark: str,
    domain: str,
    seed: int,
    source_hash: str,
    train: list[EvolutionTaskPair],
    validation: list[EvolutionTaskPair],
    clean_test: list[TaskManifest],
) -> EvolutionSplitManifest:
    return EvolutionSplitManifest(
        benchmark=benchmark,
        domain=domain,
        seed=seed,
        source_hash=source_hash,
        train=train,
        validation=validation,
        clean_test=clean_test,
    )
