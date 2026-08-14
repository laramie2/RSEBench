from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from rsebench.experiments.bootstrap import BaselineFingerprint
from rsebench.experiments.preflight import load_experiment_matrix, preflight_matrix


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _fixture_project(tmp_path: Path) -> tuple[Path, Path, BaselineFingerprint]:
    root = tmp_path / "project"
    (root / "src/rsebench").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "benchmark").mkdir()
    (root / "configs").mkdir()
    (root / "src/rsebench/__init__.py").write_text("", encoding="utf-8")
    (root / "scripts/run_fixture.py").write_text("# fixture\n", encoding="utf-8")
    seed = root / "benchmark/seed.md"
    seed.write_text("seed skill\n", encoding="utf-8")
    provider = root / "configs/provider.yaml"
    provider.write_text(
        yaml.safe_dump(
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_env": "FIXTURE_API_KEY",
                "temperature": 0.0,
                "thinking": "disabled",
            }
        ),
        encoding="utf-8",
    )
    task = lambda task_id: {
        "task_id": task_id,
        "benchmark": "fixture",
        "domain": "document",
        "prompt": task_id,
        "gold_answers": ["answer"],
        "source_hash": _hash(task_id),
    }
    manifest = root / "benchmark/fixture.json"
    manifest.write_text(
        json.dumps(
            {
                "benchmark": "fixture",
                "domain": "document",
                "seed": 7,
                "source_hash": _hash("split"),
                "train": [task("train")],
                "validation": [task("validation")],
                "clean_test": [task("test")],
                "metadata": {
                    "qualification_version": "clean-qualification-v2",
                    "runtime": {"workers": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    matrix = root / "configs/matrix.yaml"
    matrix.write_text(
        yaml.safe_dump(
            {
                "schema_version": "rsebench.experiment-matrix.v1",
                "qualification_version": "clean-qualification-v2",
                "stage": "clean",
                "method_seeds": [20260813, 20260814, 20260815],
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "temperature": 0.0,
                "thinking": "disabled",
                "provider_config": "configs/provider.yaml",
                "output_root": "outputs/fixture",
                "cells": [
                    {
                        "key": "fixture",
                        "benchmark": "fixture",
                        "baseline": "fixture",
                        "launcher": "scripts/run_fixture.py",
                        "manifest": "benchmark/fixture.json",
                        "seed_skill": "benchmark/seed.md",
                        "seed_skill_argument": True,
                        "task_counts": {
                            "train": 1,
                            "validation": 1,
                            "clean_test": 1,
                        },
                        "runtime": {"workers": 1},
                        "adapter_key": "fixture",
                        "adapter_max_parallel": 2,
                        "mutable_resource_keys": [],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "RSEBench Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fixture")
    fingerprint = BaselineFingerprint(
        baseline="fixture",
        repository="https://example.com/fixture.git",
        upstream_revision="1" * 40,
        patch_paths=[],
        patch_hashes=[],
        patchset_hash="2" * 64,
        python_version="3.13.5",
        fingerprint="3" * 64,
    )
    return root, matrix, fingerprint


def test_preflight_builds_three_identities_without_provider_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared-but-never-read")

    report = preflight_matrix(
        matrix,
        project_root=root,
        package_file=root / "src/rsebench/__init__.py",
        fingerprint_resolver=lambda baseline: fingerprint,
    )

    assert report.provider_calls == 0
    assert report.all_ready is True
    assert len(report.units) == 3
    assert len({unit.identity.experiment_id for unit in report.units}) == 3
    assert all(unit.task_order_hash == report.units[0].task_order_hash for unit in report.units)
    assert all(unit.scheduled.mutable_resource_keys == [] for unit in report.units)
    assert all(unit.scheduled.identity == unit.identity for unit in report.units)
    assert len({unit.scheduled.output_dir for unit in report.units}) == 3
    assert report.provider_configuration.credential_name == "FIXTURE_API_KEY"
    assert report.provider_configuration.credential_declared is True
    assert not (root / "outputs/fixture").exists()


def test_preflight_rejects_dirty_repository_before_identity_generation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    (root / "scripts/run_fixture.py").write_text("# dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="clean git worktree"):
        preflight_matrix(
            matrix,
            project_root=root,
            package_file=root / "src/rsebench/__init__.py",
            fingerprint_resolver=lambda baseline: fingerprint,
        )


def test_preflight_rejects_output_outside_project_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    payload = yaml.safe_load(matrix.read_text(encoding="utf-8"))
    payload["output_root"] = "../escaped"
    matrix.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    _git(root, "add", str(matrix.relative_to(root)))
    _git(root, "commit", "-q", "-m", "change output")

    with pytest.raises(ValueError, match="output_root must be inside"):
        preflight_matrix(
            matrix,
            project_root=root,
            package_file=root / "src/rsebench/__init__.py",
            fingerprint_resolver=lambda baseline: fingerprint,
        )


def test_clean_v2_matrix_declares_four_portable_cells() -> None:
    matrix = load_experiment_matrix(
        PROJECT_ROOT / "configs/experiments/clean-v2.yaml"
    )

    assert [cell.benchmark for cell in matrix.cells] == [
        "spreadsheetbench_verified",
        "officeqa_full",
        "webshop",
        "skilllearnbench",
    ]
    assert all(
        cell.manifest.startswith("benchmark/validation/clean_qualification_v2/")
        for cell in matrix.cells
    )
    skillopt = [cell for cell in matrix.cells if cell.baseline == "skillopt"]
    assert len(skillopt) == 2
    assert all(cell.mutable_resource_keys == [] for cell in skillopt)
    skilllearn = matrix.cells[-1]
    assert skilllearn.family == "offer-letter-generator"
    assert "{method_seed}" in skilllearn.mutable_resource_keys[0]
