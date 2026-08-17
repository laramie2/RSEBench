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
    assert splits["skillflow_tasks"]["selection_mode"] == "frozen_ordered_groups"
    assert splits["skillflow_tasks"]["total"] == 18
    assert splits["skilllearnbench"]["active"] is False


def test_docs_preserve_skilllearn_history_and_record_validation_v1_freeze() -> None:
    roadmap = (ROOT / "docs/project-roadmap.md").read_text(encoding="utf-8")
    current_status = (
        ROOT / "docs/reports/current/current-project-status.md"
    ).read_text(encoding="utf-8")
    historical_status = (
        ROOT / "docs/archive/status-snapshots/2026-08-17-current-experiment-status.md"
    ).read_text(encoding="utf-8")

    for text in (roadmap, current_status):
        assert "SkillLearn" in text
        assert "diagnostic" in text.lower()
        assert "validation-v1" in text
    assert "SkillFlow-Task" in roadmap
    assert "operator 与 runner" in roadmap
    assert "interface-only" in current_status
    assert "Archived cumulative snapshot" in historical_status
    assert "Self-Feedback" in historical_status
