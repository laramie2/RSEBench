from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "benchmark/registry"


def _rows(name: str, key: str) -> dict:
    return yaml.safe_load((REGISTRY / name).read_text(encoding="utf-8"))[key]


def test_skillflow_is_the_fourth_active_clean_domain() -> None:
    benchmarks = _rows("benchmarks.yaml", "benchmarks")
    active_core1 = {
        name for name, row in benchmarks.items()
        if row.get("active") and row.get("tier") == "core1"
    }

    assert active_core1 == {
        "spreadsheetbench_verified",
        "officeqa_full",
        "webshop",
        "skillflow_tasks",
    }
    assert benchmarks["skillflow_tasks"]["primary_method"] == "skillflow"
    assert benchmarks["skillflow_tasks"]["noise_ready"] is False
    assert "operators" not in benchmarks["skillflow_tasks"]
    assert benchmarks["skilllearnbench"]["active"] is False
    assert benchmarks["skilllearnbench"]["tier"] == "diagnostic"
    assert benchmarks["skilllearnbench"]["historical_results_retained"] is True


def test_skillflow_method_adapter_and_split_are_active() -> None:
    methods = _rows("methods.yaml", "methods")
    adapters = _rows("adapters.yaml", "adapters")
    splits = _rows("splits.yaml", "splits")

    assert methods["skillflow"]["active"] is True
    assert methods["skillflow"]["code_status"] == "runnable_with_deepseek_adapter"
    assert adapters["skillflow"]["active"] is True
    assert adapters["skilllearn_self_feedback"]["active"] is False
    assert splits["skillflow_tasks"]["active"] is True
    assert splits["skillflow_tasks"]["selection_mode"] == "ordered_family_qualification"
    assert splits["skilllearnbench"]["active"] is False


def test_docs_preserve_skilllearn_history_and_do_not_claim_skillflow_frozen() -> None:
    roadmap = (ROOT / "docs/project-roadmap.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/reports/current-experiment-status.md").read_text(
        encoding="utf-8"
    )

    for text in (roadmap, status):
        assert "SkillLearn" in text
        assert "diagnostic" in text.lower()
        assert "two families qualify" in text
        assert "not frozen" in text.lower()
    assert "SkillFlow-Task" in roadmap
    assert "Self-Feedback" in status
