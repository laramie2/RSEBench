from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsebench.experiments.bootstrap import BaselineFingerprint
from rsebench.experiments.release import freeze_clean_release


SEEDS = (20260813, 20260814, 20260815)


def _fingerprint(*, patch_hash: str = "2" * 64) -> BaselineFingerprint:
    return BaselineFingerprint(
        baseline="skillopt",
        repository="https://example.com/skillopt.git",
        upstream_revision="1" * 40,
        patch_paths=["repair.patch"],
        patch_hashes=[patch_hash],
        patchset_hash=patch_hash,
        python_version="3.13.5",
        fingerprint=("3" * 64 if patch_hash == "2" * 64 else "4" * 64),
    )


def _release_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_root = tmp_path / "outputs/run"
    release_root = tmp_path / "releases/clean-v2"
    seed_results = []
    for index, seed in enumerate(SEEDS):
        experiment_id = f"{index + 1:x}" * 64
        result_dir = run_root / "spreadsheet" / str(seed) / "run"
        result_dir.mkdir(parents=True)
        result = {
            "identity": {"experiment_id": experiment_id},
            "method_seed": seed,
            "qualification": {
                "passed": True,
                "clean_gain": 0.1,
                "strictly_positive_gain": True,
            },
            "timing": {
                "run": {"duration_seconds": 10.0 + index, "status": "completed"},
                "stages": [
                    {
                        "name": "evolution",
                        "duration_seconds": 4.0,
                        "status": "completed",
                    }
                ],
                "tasks": [
                    {
                        "task_id": "test",
                        "duration_seconds": 1.0,
                        "status": "completed",
                    }
                ],
            },
            "token_usage": {
                "overall": {
                    "attempted_calls": 2,
                    "observed_coverage": 1.0,
                    "billed_tokens": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }
            },
        }
        (result_dir / "result.json").write_text(
            json.dumps(result), encoding="utf-8"
        )
        seed_results.append(
            {
                "method_seed": seed,
                "status": "completed",
                "experiment_id": experiment_id,
                "engineering_valid": True,
                "positive_gain": True,
                "clean_gain": 0.1,
                "path": result_dir.relative_to(run_root).as_posix(),
            }
        )
    aggregate = {
        "schema_version": "rsebench.clean-qualification-aggregate.v2",
        "method_seeds": list(SEEDS),
        "cells": {
            "spreadsheet-skillopt": {
                "expected_seeds": list(SEEDS),
                "engineering_ready": True,
                "efficacy_ready": True,
                "engineering_valid_seeds": list(SEEDS),
                "positive_gain_seeds": list(SEEDS),
                "failure_reasons": [],
                "seed_results": seed_results,
            }
        },
    }
    aggregate_path = run_root / "aggregate.json"
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
    return run_root, aggregate_path, release_root


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_release_is_deterministic_and_baseline_fingerprint_changes_id(
    tmp_path: Path,
) -> None:
    run_root, aggregate_path, release_root = _release_fixture(tmp_path)

    first = freeze_clean_release(
        run_root=run_root,
        aggregate_path=aggregate_path,
        release_root=release_root,
        run_id="clean-v2-fixture",
        baseline_fingerprints={"skillopt": _fingerprint()},
    )
    first_bytes = _tree_bytes(first.path)
    repeated = freeze_clean_release(
        run_root=run_root,
        aggregate_path=aggregate_path,
        release_root=release_root,
        run_id="clean-v2-fixture",
        baseline_fingerprints={"skillopt": _fingerprint()},
    )
    changed = freeze_clean_release(
        run_root=run_root,
        aggregate_path=aggregate_path,
        release_root=release_root,
        run_id="clean-v2-fixture",
        baseline_fingerprints={"skillopt": _fingerprint(patch_hash="9" * 64)},
    )

    assert first.release_id == repeated.release_id
    assert first_bytes == _tree_bytes(repeated.path)
    assert changed.release_id != first.release_id
    assert set(first_bytes) == {
        "aggregate.json",
        "manifest.json",
        "qualification.json",
        "report.md",
        "timing-summary.json",
        "token-summary.json",
    }


def test_release_rejects_secret_before_writing(tmp_path: Path) -> None:
    run_root, aggregate_path, release_root = _release_fixture(tmp_path)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["cells"]["spreadsheet-skillopt"]["failure_reasons"] = [
        "sk-secret-value"
    ]
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")

    with pytest.raises(ValueError, match="secret-like content"):
        freeze_clean_release(
            run_root=run_root,
            aggregate_path=aggregate_path,
            release_root=release_root,
            run_id="clean-v2-fixture",
            baseline_fingerprints={"skillopt": _fingerprint()},
        )

    assert not release_root.exists()


def test_release_requires_efficacy_and_all_three_source_results(tmp_path: Path) -> None:
    run_root, aggregate_path, release_root = _release_fixture(tmp_path)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["cells"]["spreadsheet-skillopt"]["efficacy_ready"] = False
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")

    with pytest.raises(ValueError, match="not efficacy_ready"):
        freeze_clean_release(
            run_root=run_root,
            aggregate_path=aggregate_path,
            release_root=release_root,
            run_id="clean-v2-fixture",
            baseline_fingerprints={"skillopt": _fingerprint()},
        )

    aggregate["cells"]["spreadsheet-skillopt"]["efficacy_ready"] = True
    aggregate["cells"]["spreadsheet-skillopt"]["seed_results"].pop()
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly three formal seeds"):
        freeze_clean_release(
            run_root=run_root,
            aggregate_path=aggregate_path,
            release_root=release_root,
            run_id="clean-v2-fixture",
            baseline_fingerprints={"skillopt": _fingerprint()},
        )
