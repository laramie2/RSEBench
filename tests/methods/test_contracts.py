from __future__ import annotations

import pytest

from rsebench.datasets import EvidenceReference
from rsebench.methods import (
    HarnessIdentity,
    PatchIdentity,
    ProviderIdentity,
    build_method_release,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _release(**overrides):
    values = {
        "release_id": "example-validation-v1",
        "method": "example",
        "status": "active",
        "upstream_repository": "https://github.com/example/example.git",
        "upstream_revision": "1" * 40,
        "patch_series": (
            PatchIdentity(
                uri="rsebench-project://methods/validated/example/patches/fix.patch",
                sha256=HASH_A,
                purpose="compatibility",
            ),
        ),
        "harness": HarnessIdentity(
            entrypoint="example.runner:main",
            version="validation-v1",
            fingerprint=HASH_B,
        ),
        "provider": ProviderIdentity(
            family="openai-compatible",
            model="deepseek-v4-flash",
            adapter="example.deepseek",
        ),
        "environment_lock": (
            "rsebench-project://methods/validated/example/integration/environment.lock"
        ),
        "supported_datasets": ("example-dataset-validation-v1",),
        "clean_evidence": (
            EvidenceReference(
                uri="rsebench-project://releases/example-clean.json",
                sha256=HASH_A,
                kind="clean-control",
            ),
        ),
        "smoke_command": ("python", "-m", "example.smoke"),
        "baseline_fingerprint": HASH_B,
    }
    values.update(overrides)
    return build_method_release(**values)


def test_method_release_rejects_non_https_upstream() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _release(upstream_repository="git@github.com:example/example.git")


def test_method_release_rejects_duplicate_dataset_identity() -> None:
    with pytest.raises(ValueError, match="duplicate supported dataset"):
        _release(
            supported_datasets=(
                "example-dataset-validation-v1",
                "example-dataset-validation-v1",
            )
        )


def test_method_release_is_frozen_and_hash_verified() -> None:
    release = _release()

    with pytest.raises(Exception):
        release.status = "validated_inactive"  # type: ignore[misc]
    payload = release.model_dump(mode="json")
    payload["baseline_fingerprint"] = HASH_A
    with pytest.raises(ValueError, match="content hash differs"):
        type(release).model_validate(payload)
