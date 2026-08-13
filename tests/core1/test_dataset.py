from __future__ import annotations

from pathlib import Path

from rsebench.contracts import TaskManifest
from rsebench.core1.dataset import (
    build_core1_pair,
    build_core1_split,
    make_split_paths_portable,
    rehash_task,
    resolve_split_paths,
)
from rsebench.core1.materialize import load_core1_noise_profile


ROOT = Path(__file__).parents[2]


def task(task_id: str, prompt: str = "clean") -> TaskManifest:
    return rehash_task(
        TaskManifest(
            task_id=task_id,
            benchmark="webshop",
            domain="interactive",
            prompt=prompt,
            verifier="webshop_reward_v1",
            source_hash="0" * 64,
            metadata={"goal_idx": int(task_id.rsplit("_", 1)[1])},
        )
    )


def test_runtime_pair_is_identity_payload_with_explicit_runtime_noise() -> None:
    profile = load_core1_noise_profile(ROOT / "configs/core1/webshop/N3.yaml")
    clean = task("goal_1")

    pair = build_core1_pair(clean=clean, noisy=clean, profile=profile)

    assert pair.clean.source_hash == pair.noisy.source_hash
    assert pair.noise.operator == "webshop_n3_omit_constraint_event"
    assert pair.noise.channel.value == "C3"
    assert pair.noise.mechanism.value == "M3"
    assert pair.noise.metadata["materialization"] == "runtime_hook"


def test_static_pair_hashes_changed_prompt_and_builds_disjoint_split() -> None:
    profile = load_core1_noise_profile(ROOT / "configs/core1/webshop/N1.yaml")
    clean = task("goal_1")
    noisy = rehash_task(clean.model_copy(update={"prompt": "clean\nnoisy note"}))
    pair = build_core1_pair(clean=clean, noisy=noisy, profile=profile)

    split = build_core1_split(
        profile=profile,
        train=[pair],
        validation=[],
        clean_test=[task("goal_2")],
    )

    assert pair.clean.source_hash != pair.noisy.source_hash
    assert pair.noise.metadata["materialization"] == "frozen_pair"
    assert split.source_hash != pair.clean.source_hash
    assert split.clean_test[0].task_id == "goal_2"


def test_core1_split_paths_round_trip_without_machine_absolute_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    methods_root = tmp_path / "methods"
    for root in (project_root, data_root, methods_root):
        root.mkdir()
    workbook = data_root / "materialized/book.xlsx"
    workbook.parent.mkdir()
    workbook.write_bytes(b"book")
    fixture = project_root / "benchmark/core1/static_data/fixture.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{}", encoding="utf-8")
    clean = rehash_task(
        TaskManifest(
            task_id="goal_1",
            benchmark="webshop",
            domain="interactive",
            prompt="clean",
            verifier="webshop_reward_v1",
            source_hash="0" * 64,
            artifact_path=str(workbook),
            metadata={"retrieval_fixture": str(fixture)},
        ),
        artifact_hash="a" * 64,
    )
    profile = load_core1_noise_profile(ROOT / "configs/core1/webshop/N3.yaml")
    pair = build_core1_pair(clean=clean, noisy=clean, profile=profile)
    split = build_core1_split(
        profile=profile,
        train=[pair],
        validation=[],
        clean_test=[task("goal_2")],
    )

    portable = make_split_paths_portable(
        split,
        project_root=project_root,
        data_root=data_root,
        methods_root=methods_root,
    )
    encoded = portable.model_dump_json()

    assert str(tmp_path) not in encoded
    assert portable.train[0].clean.artifact_path == (
        "rsebench-data://materialized/book.xlsx"
    )
    assert portable.train[0].clean.metadata["retrieval_fixture"] == (
        "rsebench-project://benchmark/core1/static_data/fixture.json"
    )
    resolved = resolve_split_paths(
        portable,
        project_root=project_root,
        data_root=data_root,
        methods_root=methods_root,
    )
    assert resolved.train[0].clean.artifact_path == str(workbook.resolve())
    assert resolved.train[0].clean.metadata["retrieval_fixture"] == str(
        fixture.resolve()
    )
    assert resolved.source_hash == portable.source_hash


def test_task_hash_does_not_depend_on_local_artifact_locator() -> None:
    first = TaskManifest(
        task_id="portable",
        benchmark="webshop",
        domain="interactive",
        prompt="same prompt",
        verifier="webshop_reward_v1",
        source_hash="0" * 64,
        artifact_path="/machine-a/book.xlsx",
        metadata={"gold_workbook_path": "/machine-a/gold.xlsx"},
    )
    second = first.model_copy(
        update={
            "artifact_path": "/machine-b/book.xlsx",
            "metadata": {"gold_workbook_path": "/machine-b/gold.xlsx"},
        }
    )

    assert rehash_task(first, artifact_hash="b" * 64).source_hash == rehash_task(
        second, artifact_hash="b" * 64
    ).source_hash
