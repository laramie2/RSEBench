from __future__ import annotations

from pathlib import Path

from rsebench.core1.contracts import load_core1_profiles
from rsebench.registry import load_registry


ROOT = Path(__file__).parents[2]
REGISTRY = ROOT / "benchmark" / "registry"


def test_active_core1_set_and_primary_methods_are_exact() -> None:
    profiles = load_core1_profiles(REGISTRY)

    assert {
        name: (profile.domain, profile.primary_method)
        for name, profile in profiles.items()
    } == {
        "spreadsheetbench_verified": ("spreadsheet", "skillopt"),
        "officeqa_full": ("document", "skillopt"),
        "skilllearnbench": ("skill_learning", "skilllearn_self_feedback"),
        "webshop": ("interactive", "skilladaptor"),
    }


def test_every_core1_domain_has_one_operator_per_stage() -> None:
    profiles = load_core1_profiles(REGISTRY)

    assert all(set(profile.operators) == {"N1", "N2", "N3", "N4"} for profile in profiles.values())
    assert all(profile.domain != "math" for profile in profiles.values())
    assert len(
        {
            operator.operator_id
            for profile in profiles.values()
            for operator in profile.operators.values()
        }
    ) == 16


def test_math_rows_are_retained_but_inactive() -> None:
    benchmarks = load_registry(REGISTRY / "benchmarks.yaml")["benchmarks"]
    math_rows = [row for row in benchmarks.values() if row["domain"] == "math"]

    assert math_rows
    assert all(row.get("active") is False for row in math_rows)


def test_new_upstream_commits_are_pinned() -> None:
    methods = load_registry(REGISTRY / "methods.yaml")["methods"]

    assert methods["skilllearn_self_feedback"]["commit"] == "a0da045a8bf64b8a8ff20730c4d6ef10dc4e2c5b"
    assert methods["skilladaptor"]["commit"] == "b26d1ab5a798f07e53048b5ff509e8535e9fa228"
    assert methods["rethinkskill"]["commit"] == "4138419afc00a1fa3ff0885c0bb1618e18258354"


def test_active_adapters_use_deepseek_v4_flash() -> None:
    adapters = load_registry(REGISTRY / "adapters.yaml")["adapters"]
    active = {name: row for name, row in adapters.items() if row.get("active")}

    assert set(active) == {
        "skillopt",
        "skillflow",
        "skilladaptor",
    }
    assert all(row["model"] == "deepseek-v4-flash" for row in active.values())
