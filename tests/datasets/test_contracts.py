from __future__ import annotations

from pathlib import Path

import pytest

from rsebench.contracts import TaskManifest
from rsebench.datasets import BenchmarkDataset, build_dataset_release


HASH_A = "a" * 64
HASH_B = "b" * 64


def _task(task_id: str, source_hash: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="example_benchmark",
        domain="example_domain",
        prompt=f"Solve {task_id}",
        source_hash=source_hash,
        verifier="example_verifier",
        artifact_path=f"rsebench-data://benchmarks/example_domain/example_benchmark/raw/{task_id}",
    )


def test_dataset_release_rejects_unknown_partition_task() -> None:
    with pytest.raises(ValueError, match="unknown task.*missing"):
        build_dataset_release(
            release_id="example-validation-v1",
            domain="example_domain",
            benchmark="example_benchmark",
            benchmark_version="1",
            loader="example_loader",
            verifier="example_verifier",
            tasks={"t1": _task("t1", HASH_A)},
            partitions={"test": ("t1", "missing")},
        )


def test_dataset_release_preserves_group_order() -> None:
    release = build_dataset_release(
        release_id="example-validation-v1",
        domain="example_domain",
        benchmark="example_benchmark",
        benchmark_version="1",
        loader="example_loader",
        verifier="example_verifier",
        tasks={"t1": _task("t1", HASH_A), "t2": _task("t2", HASH_B)},
        groups={"family-a": ("t2", "t1")},
    )

    dataset = BenchmarkDataset(release)

    assert dataset.group_names() == ("family-a",)
    assert tuple(task.task_id for task in dataset.group("family-a")) == ("t2", "t1")


def test_dataset_release_rejects_duplicate_membership() -> None:
    with pytest.raises(ValueError, match="duplicate task.*t1"):
        build_dataset_release(
            release_id="example-validation-v1",
            domain="example_domain",
            benchmark="example_benchmark",
            benchmark_version="1",
            loader="example_loader",
            verifier="example_verifier",
            tasks={"t1": _task("t1", HASH_A)},
            groups={"family-a": ("t1", "t1")},
        )


def test_dataset_release_is_frozen() -> None:
    release = build_dataset_release(
        release_id="example-validation-v1",
        domain="example_domain",
        benchmark="example_benchmark",
        benchmark_version="1",
        loader="example_loader",
        verifier="example_verifier",
        tasks={"t1": _task("t1", HASH_A)},
    )

    with pytest.raises(Exception):
        release.release_id = "changed"  # type: ignore[misc]


def test_task_identity_must_match_mapping_key() -> None:
    with pytest.raises(ValueError, match="task mapping key differs"):
        build_dataset_release(
            release_id="example-validation-v1",
            domain="example_domain",
            benchmark="example_benchmark",
            benchmark_version="1",
            loader="example_loader",
            verifier="example_verifier",
            tasks={"wrong": _task("t1", HASH_A)},
        )


def test_release_content_hash_is_path_independent(tmp_path: Path) -> None:
    first = build_dataset_release(
        release_id="example-validation-v1",
        domain="example_domain",
        benchmark="example_benchmark",
        benchmark_version="1",
        loader="example_loader",
        verifier="example_verifier",
        tasks={"t1": _task("t1", HASH_A)},
    )
    second = build_dataset_release(
        release_id="example-validation-v1",
        domain="example_domain",
        benchmark="example_benchmark",
        benchmark_version="1",
        loader="example_loader",
        verifier="example_verifier",
        tasks={"t1": _task("t1", HASH_A)},
    )

    assert first.content_hash == second.content_hash
    assert str(tmp_path) not in first.model_dump_json()
