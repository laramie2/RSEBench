from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsebench.core1.materialize import (
    freeze_static_pair,
    load_core1_noise_profile,
    materialize_core1_profile,
)
from rsebench.evidence import RuntimeNoiseSpec


ROOT = Path(__file__).parents[2]


def profile_paths() -> list[Path]:
    return sorted((ROOT / "configs" / "core1").glob("*/*.yaml"))


def test_all_16_core1_profiles_are_strict_and_complete() -> None:
    paths = profile_paths()

    assert len(paths) == 16
    profiles = [load_core1_noise_profile(path) for path in paths]
    assert {
        (profile.benchmark, profile.stage.value) for profile in profiles
    } == {
        (benchmark, stage)
        for benchmark in (
            "spreadsheetbench_verified",
            "officeqa_full",
            "skilllearnbench",
            "webshop",
        )
        for stage in ("N1", "N2", "N3", "N4")
    }
    assert all(profile.model == "deepseek-v4-flash" for profile in profiles)
    assert all(profile.thinking is False for profile in profiles)


@pytest.mark.parametrize("stage", ["N3", "N4"])
def test_runtime_profile_materializes_public_spec(tmp_path: Path, stage: str) -> None:
    path = ROOT / "configs/core1/webshop" / f"{stage}.yaml"

    artifact = materialize_core1_profile(path, output_root=tmp_path)

    payload = json.loads(artifact.read_text())
    spec = RuntimeNoiseSpec.model_validate(payload)
    assert spec.stage.value == stage
    assert spec.budget == 1
    assert spec.failure_policy == "record_inapplicable"


def test_static_pair_manifest_has_hashes_gates_and_no_test_leak(tmp_path: Path) -> None:
    profile = load_core1_noise_profile(
        ROOT / "configs/core1/officeqa/N1.yaml"
    )

    manifest_path = freeze_static_pair(
        profile=profile,
        task_id="train-1",
        clean_payload={"question": "clean"},
        noisy_payload={"question": "clean\nanalyst note"},
        output_root=tmp_path,
        clean_test_ids={"test-1"},
        gates={
            "structural_valid": True,
            "label_invariant": True,
            "solvable": True,
            "answer_leak_free": True,
        },
    )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["task_id"] == "train-1"
    assert len(manifest["clean_hash"]) == 64
    assert len(manifest["noisy_hash"]) == 64
    assert manifest["clean_hash"] != manifest["noisy_hash"]
    assert manifest["source_revision"]
    assert manifest["operator_version"] == "v1"
    assert all(manifest["gates"].values())


def test_static_pair_rejects_clean_test_id(tmp_path: Path) -> None:
    profile = load_core1_noise_profile(
        ROOT / "configs/core1/officeqa/N2.yaml"
    )
    with pytest.raises(ValueError, match="clean test"):
        freeze_static_pair(
            profile=profile,
            task_id="test-1",
            clean_payload={"x": 1},
            noisy_payload={"x": 2},
            output_root=tmp_path,
            clean_test_ids={"test-1"},
            gates={
                "structural_valid": True,
                "label_invariant": True,
                "solvable": True,
                "answer_leak_free": True,
            },
        )
