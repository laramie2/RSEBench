from pathlib import Path

from rsebench.registry import load_registry, validate_registries


ROOT = Path(__file__).parents[1]


def test_every_method_has_full_commit_and_repository():
    methods = load_registry(ROOT / "benchmark/registry/methods.yaml")["methods"]
    assert {"trace2skill", "skillopt", "skillgrad", "evoskill"} <= set(methods)
    assert all(len(row["commit"]) == 40 for row in methods.values())
    assert all(
        row["repository"].startswith("https://github.com/")
        for row in methods.values()
    )


def test_registries_are_cross_reference_valid():
    validate_registries(ROOT / "benchmark/registry")
