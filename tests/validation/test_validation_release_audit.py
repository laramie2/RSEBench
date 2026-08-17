from __future__ import annotations

import re
from pathlib import Path

import yaml

from rsebench.validation import ValidationCatalogs, load_and_expand


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "configs/validation/validation-v1.yaml"
REPORT = ROOT / "docs/reports/current/2026-08-17-validation-v1-freeze.md"


def test_validation_release_has_exact_frozen_scope() -> None:
    catalogs = ValidationCatalogs.load(ROOT)
    cells = load_and_expand(MATRIX)

    assert len(catalogs.datasets) == 4
    assert len(catalogs.methods.active_releases()) == 4
    assert {release.method for release in catalogs.methods.active_releases()} == {
        "skillopt",
        "skilladaptor",
        "skillflow",
    }
    assert tuple(catalogs.plugins) == ("N1", "N2", "N3", "N4")
    assert len(cells) == 16


def test_frozen_manifests_contain_no_local_paths_or_secret_values() -> None:
    paths = [
        MATRIX,
        *ROOT.glob("benchmark/datasets/*/*/releases/validation-v1/manifest.json"),
        *ROOT.glob("methods/validated/*/releases/*.json"),
        *ROOT.glob("methods/validated/*/method.yaml"),
    ]

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "/home/" not in text, path
        assert "api_key" not in text.casefold(), path
        assert "secret_key" not in text.casefold(), path
        assert "BEGIN PRIVATE KEY" not in text, path


def test_report_links_and_registry_lifecycle_are_current() -> None:
    text = REPORT.read_text(encoding="utf-8")
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
    local_links = [link for link in links if "://" not in link and not link.startswith("#")]
    assert local_links
    for link in local_links:
        target = (REPORT.parent / link.split("#", 1)[0]).resolve()
        assert target.exists(), (link, target)

    methods = yaml.safe_load(
        (ROOT / "benchmark/registry/methods.yaml").read_text(encoding="utf-8")
    )["methods"]
    benchmarks = yaml.safe_load(
        (ROOT / "benchmark/registry/benchmarks.yaml").read_text(encoding="utf-8")
    )["benchmarks"]
    assert methods["skillopt"]["lifecycle"] == "validated"
    assert methods["skilladaptor"]["lifecycle"] == "validated"
    assert methods["skillflow"]["lifecycle"] == "validated"
    assert methods["skilllearn_self_feedback"]["lifecycle"] == "validated_inactive"
    assert methods["rethinkskill"]["lifecycle"] == "candidate"
    assert benchmarks["skillflow_tasks"]["clean_selection_status"] == (
        "frozen_validation_v1"
    )
    assert benchmarks["skillflow_tasks"]["noise_ready"] is False
