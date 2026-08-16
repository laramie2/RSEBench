from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from rsebench.experiments.bootstrap import (
    bootstrap_registered_baselines,
    build_baseline_fingerprint,
    load_patch_series,
    verify_registered_baselines,
    verify_baseline,
)


ROOT = Path(__file__).parents[2]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _fixture_checkout(tmp_path: Path) -> tuple[Path, str, Path]:
    checkout = tmp_path / "method"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    _git(checkout, "config", "user.email", "tests@example.com")
    _git(checkout, "config", "user.name", "RSEBench Tests")
    (checkout / "value.txt").write_text("upstream\n", encoding="utf-8")
    _git(checkout, "add", "value.txt")
    _git(checkout, "commit", "-q", "-m", "upstream")
    revision = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "remote", "add", "origin", "https://example.com/method.git")

    series_root = tmp_path / "series"
    series_root.mkdir()
    patch = series_root / "provider.patch"
    patch.write_text(
        """diff --git a/value.txt b/value.txt
index 8ca3f8d..893adcd 100644
--- a/value.txt
+++ b/value.txt
@@ -1 +1 @@
-upstream
+patched
""",
        encoding="utf-8",
    )
    _git(checkout, "apply", str(patch))
    series_path = series_root / "series.yaml"
    fingerprint = build_baseline_fingerprint(
        name="fixture",
        repository="https://example.com/method.git",
        revision=revision,
        patch_paths=[patch],
        python_version="3.13.5",
    )
    series_path.write_text(
        yaml.safe_dump(
            {
                "baseline": "fixture",
                "upstream_revision": revision,
                "patches": [
                    {
                        "path": patch.name,
                        "sha256": fingerprint.patch_hashes[0],
                        "purpose": "provider",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return checkout, revision, series_path


def test_patch_order_and_bytes_change_fingerprint(tmp_path: Path) -> None:
    first_patch = tmp_path / "first.patch"
    second_patch = tmp_path / "second.patch"
    first_patch.write_bytes(b"first\n")
    second_patch.write_bytes(b"second\n")
    common = {
        "name": "skillopt",
        "repository": "https://github.com/microsoft/SkillOpt.git",
        "revision": "4" * 40,
        "python_version": "3.13.5",
    }

    first = build_baseline_fingerprint(
        **common, patch_paths=[first_patch, second_patch]
    )
    reordered = build_baseline_fingerprint(
        **common, patch_paths=[second_patch, first_patch]
    )
    second_patch.write_bytes(b"changed\n")
    changed = build_baseline_fingerprint(
        **common, patch_paths=[first_patch, second_patch]
    )

    assert first.patchset_hash != reordered.patchset_hash
    assert first.fingerprint != reordered.fingerprint
    assert first.patchset_hash != changed.patchset_hash
    assert first.fingerprint != changed.fingerprint


def test_verify_baseline_accepts_exact_replay_and_rejects_extra_diff(
    tmp_path: Path,
) -> None:
    checkout, revision, series_path = _fixture_checkout(tmp_path)
    series = load_patch_series(series_path)

    verified = verify_baseline(
        checkout,
        series,
        series_path=series_path,
        repository="https://example.com/method.git",
        revision=revision,
        python_version="3.13.5",
    )

    assert verified.baseline == "fixture"
    assert verified.upstream_revision == revision
    assert len(verified.fingerprint) == 64
    (checkout / "value.txt").write_text("patched\nunregistered\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unregistered baseline changes"):
        verify_baseline(
            checkout,
            series,
            series_path=series_path,
            repository="https://example.com/method.git",
            revision=revision,
            python_version="3.13.5",
        )


def test_load_patch_series_rejects_stale_hash(tmp_path: Path) -> None:
    _, _, series_path = _fixture_checkout(tmp_path)
    payload = yaml.safe_load(series_path.read_text(encoding="utf-8"))
    payload["patches"][0]["sha256"] = "0" * 64
    series_path.write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="patch hash mismatch"):
        load_patch_series(series_path)


def test_registered_bootstrap_applies_patches_then_verifies(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    checkout, revision, series_path = _fixture_checkout(fixture_root)
    project = tmp_path / "project"
    methods_root = project / "methods/external"
    methods_root.mkdir(parents=True)
    checkout.rename(methods_root / "fixture")
    pinned_series = project / "patches/baselines/fixture"
    pinned_series.parent.mkdir(parents=True)
    series_path.parent.rename(pinned_series)
    series_path = pinned_series / "series.yaml"
    registry = project / "benchmark/registry"
    registry.mkdir(parents=True)
    (registry / "methods.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "methods": {
                    "fixture": {
                        "active": True,
                        "repository": "https://example.com/method.git",
                        "commit": revision,
                        "git_lfs": False,
                        "native_domains": ["document"],
                        "code_status": "runnable",
                        "patch_series": "patches/baselines/fixture/series.yaml",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    patch = pinned_series / "provider.patch"
    _git(methods_root / "fixture", "apply", "--reverse", str(patch))

    bootstrapped = bootstrap_registered_baselines(
        project_root=project,
        methods_root=methods_root,
    )
    verified = verify_registered_baselines(
        project_root=project,
        methods_root=methods_root,
    )

    assert bootstrapped["fixture"].fingerprint == verified["fixture"].fingerprint
    assert (methods_root / "fixture/value.txt").read_text() == "patched\n"


def test_registered_skillflow_patch_series_is_provider_first() -> None:
    registry = yaml.safe_load(
        (ROOT / "benchmark/registry/methods.yaml").read_text(encoding="utf-8")
    )["methods"]
    series_path = ROOT / registry["skillflow"]["patch_series"]

    series = load_patch_series(series_path)
    patch_text = (series_path.parent / series.patches[0].path).read_text(
        encoding="utf-8"
    )

    assert series.baseline == "skillflow"
    assert series.upstream_revision == "7b49ff5a7e26cd7706e959bfa0dba4746d18440d"
    assert series.patches[0].purpose == "provider"
    assert "libs/harbor_noinstall_agents/deepseek_api.py" in patch_text
    assert [patch.purpose for patch in series.patches] == [
        "provider",
        "evidence",
        "compatibility",
        "compatibility",
    ]
    evidence_text = (series_path.parent / series.patches[1].path).read_text(
        encoding="utf-8"
    )
    assert "record_token_event" in evidence_text
    assert "run_patch_operation_with_history" in evidence_text
    assert "diff --git a/.gitignore b/.gitignore" in evidence_text
    compatibility_text = (series_path.parent / series.patches[2].path).read_text(
        encoding="utf-8"
    )
    assert "await Job.create(group_config)" in compatibility_text
    worker_budget_text = (series_path.parent / series.patches[3].path).read_text(
        encoding="utf-8"
    )
    assert "max_tokens=self.max_tokens" in worker_budget_text
