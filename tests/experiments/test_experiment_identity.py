from __future__ import annotations

import re

from rsebench.experiments.bootstrap import BaselineFingerprint
from rsebench.experiments.contracts import (
    ExperimentIdentityInput,
    build_attempt_identity,
    build_experiment_identity,
)


def _baseline() -> BaselineFingerprint:
    return BaselineFingerprint(
        baseline="skillopt",
        repository="https://github.com/microsoft/SkillOpt.git",
        upstream_revision="1" * 40,
        patch_paths=["provider.patch"],
        patch_hashes=["2" * 64],
        patchset_hash="3" * 64,
        python_version="3.13.5",
        fingerprint="4" * 64,
    )


def _inputs() -> ExperimentIdentityInput:
    return ExperimentIdentityInput(
        repository_commit="5" * 40,
        baseline=_baseline(),
        environment_hash="6" * 64,
        manifest_hash="7" * 64,
        dataset_hashes={"tasks": "8" * 64, "artifacts": "9" * 64},
        seed_skill_hash="a" * 64,
        model="deepseek-v4-flash",
        provider="deepseek",
        runtime={"workers": 2, "limits": {"turns": 12, "tokens": 4096}},
        benchmark="officeqa_full",
        stage="clean",
        method_seed=20260813,
    )


def test_experiment_identity_is_canonical_and_input_sensitive() -> None:
    inputs = _inputs()
    first = build_experiment_identity(inputs)
    reordered = build_experiment_identity(
        inputs.model_copy(
            update={
                "dataset_hashes": {
                    "artifacts": "9" * 64,
                    "tasks": "8" * 64,
                },
                "runtime": {
                    "limits": {"tokens": 4096, "turns": 12},
                    "workers": 2,
                },
            }
        )
    )
    changed_seed = build_experiment_identity(
        inputs.model_copy(update={"method_seed": 20260814})
    )
    changed_patchset = build_experiment_identity(
        inputs.model_copy(
            update={
                "baseline": inputs.baseline.model_copy(
                    update={"patchset_hash": "b" * 64}
                )
            }
        )
    )
    changed_manifest = build_experiment_identity(
        inputs.model_copy(update={"manifest_hash": "c" * 64})
    )

    assert first.experiment_id == reordered.experiment_id
    assert re.fullmatch(r"[0-9a-f]{64}", first.experiment_id)
    assert changed_seed.experiment_id != first.experiment_id
    assert changed_patchset.experiment_id != first.experiment_id
    assert changed_manifest.experiment_id != first.experiment_id


def test_attempts_preserve_experiment_and_increment_number() -> None:
    identity = build_experiment_identity(_inputs())

    first = build_attempt_identity(identity, attempt_number=1)
    retry = build_attempt_identity(identity, attempt_number=2)

    assert first.experiment_id == retry.experiment_id == identity.experiment_id
    assert first.attempt_number == 1
    assert retry.attempt_number == 2
    assert first.attempt_id != retry.attempt_id
    assert first.attempt_id.version == retry.attempt_id.version == 4
