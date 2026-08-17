from __future__ import annotations

from pathlib import Path

import pytest

from rsebench.methods import MethodCatalog


ROOT = Path(__file__).resolve().parents[2]


def test_validation_v1_has_three_active_method_families_and_four_releases() -> None:
    catalog = MethodCatalog.load(ROOT / "methods")
    active = catalog.active_releases()

    assert {row.method for row in active} == {"skillopt", "skilladaptor", "skillflow"}
    assert len(active) == 4
    assert {row.release_id for row in active} == {
        "skillopt-spreadsheet-validation-v1",
        "skillopt-officeqa-validation-v1",
        "skilladaptor-webshop-validation-v1",
        "skillflow-validation-v1",
    }


def test_active_release_fingerprints_are_exact() -> None:
    catalog = MethodCatalog.load(ROOT / "methods")

    assert {
        row.release_id: row.baseline_fingerprint
        for row in catalog.active_releases()
    } == {
        "skillopt-spreadsheet-validation-v1": (
            "b209b2686c902166e31062e6473075f5a87d1058759d81ce66f6864efafcc3a3"
        ),
        "skillopt-officeqa-validation-v1": (
            "bbf775793ff2cc1e9f22b2c530a82957ba87d05749a50f6f53657c01549d9033"
        ),
        "skilladaptor-webshop-validation-v1": (
            "ebcfa0ccc76c5589bd95da3e7ae21a4065dd5e060f9abc207954e4cd750ef014"
        ),
        "skillflow-validation-v1": (
            "e329b830e2a65748f5fc8736a2dd7f56781a28f400281b9ee608a85c98aca875"
        ),
    }


def test_candidate_cannot_be_resolved_as_active() -> None:
    catalog = MethodCatalog.load(ROOT / "methods")

    with pytest.raises(ValueError, match="not active"):
        catalog.require_active("rethinkskill")


def test_skilllearn_is_validated_but_inactive() -> None:
    catalog = MethodCatalog.load(ROOT / "methods")

    assert catalog.method_status("skilllearn_self_feedback") == "validated_inactive"
    with pytest.raises(ValueError, match="not active"):
        catalog.require_active("skilllearn-self-feedback-diagnostic-v1")


def test_catalog_verifies_patch_hashes_and_resolves_legacy_source() -> None:
    catalog = MethodCatalog.load(ROOT / "methods")
    assert all(release.patch_series for release in catalog.active_releases())

    with pytest.warns(DeprecationWarning, match="legacy method source"):
        source = catalog.resolve_method_source("skillopt")
    assert source == (ROOT / "methods/external/skillopt").resolve()
