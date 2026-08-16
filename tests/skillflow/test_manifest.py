from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsebench.skillflow.manifest import (
    build_family_manifest,
    verify_input_manifest,
)


def _task(root: Path, name: str) -> Path:
    task = root / name
    for directory in ("environment", "solution", "tests"):
        (task / directory).mkdir(parents=True, exist_ok=True)
    (task / "task.toml").write_text('version = "1"\n', encoding="utf-8")
    (task / "instruction.md").write_text(f"solve {name}\n", encoding="utf-8")
    (task / "environment/Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (task / "solution/solve.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (task / "tests/test.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return task


def _family(tmp_path: Path) -> Path:
    family = tmp_path / "Document-Fraud-Detection"
    _task(family, "first")
    _task(family, "second")
    (family / "ALL_TASK_DIFFICULTY_RANKING.json").write_text(
        json.dumps(["second", "first"]), encoding="utf-8"
    )
    return family


def test_build_family_manifest_preserves_ranking_and_hashes(tmp_path: Path) -> None:
    family = _family(tmp_path)

    manifest = build_family_manifest(family, data_root=tmp_path)

    assert [task.task_id for task in manifest.tasks] == ["second", "first"]
    assert [task.order for task in manifest.tasks] == [1, 2]
    assert manifest.status == "ready"
    assert manifest.ranked_task_ids == ["second", "first"]
    assert all(len(task.task_hash) == 64 for task in manifest.tasks)
    assert manifest.tasks[0].relative_path == "Document-Fraud-Detection/second"


def test_build_family_manifest_rejects_unknown_or_unranked_tasks(
    tmp_path: Path,
) -> None:
    family = _family(tmp_path)
    ranking = family / "ALL_TASK_DIFFICULTY_RANKING.json"
    ranking.write_text(json.dumps(["first", "missing"]), encoding="utf-8")

    with pytest.raises(ValueError, match="ranking differs from valid tasks"):
        build_family_manifest(family, data_root=tmp_path)


def test_build_family_manifest_rejects_incomplete_task(tmp_path: Path) -> None:
    family = _family(tmp_path)
    (family / "second/task.toml").unlink()

    with pytest.raises(ValueError, match="ranking differs from valid tasks"):
        build_family_manifest(family, data_root=tmp_path)


def test_verify_input_manifest_detects_task_hash_drift(tmp_path: Path) -> None:
    family = _family(tmp_path)
    built = build_family_manifest(family, data_root=tmp_path)
    payload = {
        "schema_version": "rsebench.skillflow-input.v1",
        "benchmark": "skillflow_tasks",
        "baseline": "skillflow",
        "upstream_revision": "7b49ff5a7e26cd7706e959bfa0dba4746d18440d",
        "qualification_contract": "skillflow-clean-qualification-v1",
        "config_hash": "a" * 64,
        "runtime": {
            "model": "deepseek-v4-flash",
            "thinking": "disabled",
            "temperature": 0.0,
            "max_turns": 30,
            "max_completion_tokens": 2048,
            "patch_temperature": 0.2,
            "patch_max_tokens": 8192,
            "patch_max_steps": 60,
            "patch_max_observation_chars": 3000,
            "docker_image": "skillflow/harbor-cli-base:ubuntu24.04",
            "arm_timeout_seconds": 21600,
        },
        "qualification": {
            "minimum_positive_replicates": 2,
            "minimum_nonnegative_replicates": 3,
            "minimum_patch_replicates": 3,
            "minimum_skill_use_replicates": 2,
            "require_positive_pooled_full_delta": True,
            "target_qualified_families": 2,
        },
        "batch_a": [built.family],
        "batch_b": [],
        "replicates": ["r1", "r2", "r3"],
        "families": [built.model_dump(mode="json")],
        "provider_calls": 0,
    }
    (family / "second/instruction.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="task hash differs"):
        verify_input_manifest(payload, data_root=tmp_path)
