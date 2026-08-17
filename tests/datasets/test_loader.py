from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsebench.contracts import TaskManifest
from rsebench.datasets import (
    BenchmarkDataset,
    build_dataset_release,
    load_dataset_release,
    resolve_portable_uri,
)


def _release():
    task = TaskManifest(
        task_id="t1",
        benchmark="example_benchmark",
        domain="example_domain",
        prompt="Solve t1",
        source_hash="a" * 64,
        verifier="example_verifier",
        artifact_path="rsebench-data://raw/t1",
    )
    return build_dataset_release(
        release_id="example-validation-v1",
        domain="example_domain",
        benchmark="example_benchmark",
        benchmark_version="1",
        loader="example_loader",
        verifier="example_verifier",
        tasks={"t1": task},
        partitions={"test": ("t1",)},
    )


def test_release_json_round_trip(tmp_path: Path) -> None:
    release = _release()
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(release.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )

    loaded = load_dataset_release(path)

    assert loaded == release
    assert BenchmarkDataset(loaded).partition("test")[0].task_id == "t1"


def test_loader_rejects_tampered_content_hash(tmp_path: Path) -> None:
    payload = _release().model_dump(mode="json")
    payload["loader"] = "tampered"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="content hash differs"):
        load_dataset_release(path)


def test_portable_uri_prefers_canonical_root(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    target = canonical / "raw/t1"
    target.parent.mkdir(parents=True)
    target.write_text("canonical", encoding="utf-8")
    (legacy / "raw").mkdir(parents=True)
    (legacy / "raw/t1").write_text("legacy", encoding="utf-8")

    resolved = resolve_portable_uri(
        "rsebench-data://raw/t1",
        roots={"rsebench-data": canonical},
        legacy_roots={"rsebench-data": (legacy,)},
    )

    assert resolved == target.resolve()


def test_portable_uri_uses_legacy_root_with_warning(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    target = legacy / "raw/t1"
    target.parent.mkdir(parents=True)
    target.write_text("legacy", encoding="utf-8")

    with pytest.warns(DeprecationWarning, match="legacy rsebench-data root"):
        resolved = resolve_portable_uri(
            "rsebench-data://raw/t1",
            roots={"rsebench-data": canonical},
            legacy_roots={"rsebench-data": (legacy,)},
        )

    assert resolved == target.resolve()


def test_portable_uri_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        resolve_portable_uri(
            "rsebench-data://../secret",
            roots={"rsebench-data": tmp_path / "canonical"},
        )
