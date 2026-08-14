import hashlib

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution.splits import deterministic_group_split


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _task(task_id: str, group_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="spreadsheet",
        prompt=f"task {task_id}",
        gold_answers=["x"],
        source_hash=_hash(task_id),
        metadata={"group_id": group_id},
    )


def test_group_split_is_deterministic_and_has_no_group_leakage():
    tasks = [
        _task("a1", "a"),
        _task("a2", "a"),
        _task("b1", "b"),
        _task("c1", "c"),
        _task("d1", "d"),
    ]

    first = deterministic_group_split(
        tasks, seed=5, train_groups=2, validation_groups=1, test_groups=1
    )
    second = deterministic_group_split(
        list(reversed(tasks)),
        seed=5,
        train_groups=2,
        validation_groups=1,
        test_groups=1,
    )

    assert first == second
    groups = [
        {task.metadata["group_id"] for task in split}
        for split in (first.train, first.validation, first.clean_test)
    ]
    assert groups[0].isdisjoint(groups[1])
    assert groups[0].isdisjoint(groups[2])
    assert groups[1].isdisjoint(groups[2])


def test_group_split_rejects_insufficient_groups():
    with pytest.raises(ValueError, match="insufficient groups"):
        deterministic_group_split(
            [_task("a", "a")],
            seed=1,
            train_groups=1,
            validation_groups=1,
            test_groups=1,
        )
