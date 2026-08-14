import json
from pathlib import Path

import pytest

from rsebench.experiments.bootstrap import BaselineFingerprint
from rsebench.experiments.contracts import (
    ExperimentIdentityInput,
    build_attempt_identity,
    build_experiment_identity,
)
from rsebench.experiments.runtime import load_runtime_identity


def _identity():
    baseline = BaselineFingerprint(
        baseline="fixture",
        repository="https://example.com/fixture.git",
        upstream_revision="1" * 40,
        patch_paths=[],
        patch_hashes=[],
        patchset_hash="2" * 64,
        python_version="3.13.5",
        fingerprint="3" * 64,
    )
    return build_experiment_identity(
        ExperimentIdentityInput(
            repository_commit="4" * 40,
            baseline=baseline,
            environment_hash="5" * 64,
            manifest_hash="6" * 64,
            dataset_hashes={"split": "7" * 64},
            seed_skill_hash="8" * 64,
            model="deepseek-v4-flash",
            provider="deepseek",
            runtime={"workers": 1},
            benchmark="fixture",
            stage="clean",
            method_seed=20260813,
        )
    )


def test_runtime_identity_loads_scheduler_payload(monkeypatch, tmp_path: Path) -> None:
    identity = _identity()
    attempt = build_attempt_identity(identity, attempt_number=2)
    path = tmp_path / "identity.json"
    path.write_text(
        json.dumps(
            {
                "identity": identity.model_dump(mode="json"),
                "attempt": attempt.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RSEBENCH_IDENTITY_PATH", str(path))

    loaded_identity, loaded_attempt = load_runtime_identity(
        required=True,
        benchmark="fixture",
        method_seed=20260813,
    )

    assert loaded_identity == identity
    assert loaded_attempt == attempt


def test_runtime_identity_is_required_for_formal_v2(monkeypatch) -> None:
    monkeypatch.delenv("RSEBENCH_IDENTITY_PATH", raising=False)

    with pytest.raises(RuntimeError, match="formal experiment identity"):
        load_runtime_identity(
            required=True,
            benchmark="fixture",
            method_seed=20260813,
        )
