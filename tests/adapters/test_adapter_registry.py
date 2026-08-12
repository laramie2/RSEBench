from pathlib import Path

from rsebench.adapters.registry import load_adapter_registry


ROOT = Path(__file__).parents[2]


def test_registry_lists_every_runnable_method():
    registry = load_adapter_registry(ROOT / "benchmark/registry/adapters.yaml")

    assert set(registry.adapters) == {
        "trace2skill",
        "skillopt",
        "skillgrad",
        "evoskill",
        "skills_coach",
        "skillflow",
        "federatedskill",
    }
    assert all(
        spec.model == "deepseek-v4-flash" for spec in registry.adapters.values()
    )
    assert all(spec.upstream_commit for spec in registry.adapters.values())


def test_registry_declares_every_model_role():
    registry = load_adapter_registry(ROOT / "benchmark/registry/adapters.yaml")

    assert set(registry.adapters["trace2skill"].roles) == {
        "executor",
        "analysis",
        "optimizer",
    }
    assert "merger" in registry.adapters["federatedskill"].roles
