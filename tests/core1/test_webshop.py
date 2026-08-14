from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rsebench.core1.webshop import (
    build_webshop_n1_context,
    build_webshop_n2_overlay,
    parse_goal_constraints,
    select_structurally_calibrated_goals,
    select_near_match,
)


def test_webshop_core1_import_does_not_require_spreadsheet_dependencies() -> None:
    root = Path(__file__).parents[2]
    code = """
import importlib.abc
import sys
class RejectOpenpyxl(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'openpyxl' or fullname.startswith('openpyxl.'):
            raise ModuleNotFoundError('blocked optional spreadsheet dependency')
        return None
sys.meta_path.insert(0, RejectOpenpyxl())
from rsebench.core1 import build_webshop_n1_context
assert callable(build_webshop_n1_context)
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root / "src")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def goal() -> dict[str, object]:
    return {
        "goal_id": "goal-1",
        "asin": "TARGET",
        "instruction_text": (
            "Find a ceramic travel mug with color: red, size: large, "
            "and price lower than 30 dollars"
        ),
        "category": "travel mugs",
        "product_category": "Home › Kitchen › Travel Mugs",
        "attributes": ["ceramic", "leak proof"],
        "goal_options": {"color": "red", "size": "large"},
        "price_upper": 30.0,
    }


def catalog() -> list[dict[str, object]]:
    return [
        {
            "asin": "TARGET",
            "name": "Ceramic leak proof travel mug",
            "category": "travel mugs",
            "product_category": "Home › Kitchen › Travel Mugs",
            "Attributes": ["ceramic", "leak proof"],
            "options": {"color": ["red"], "size": ["large"]},
            "pricing": [24.0],
        },
        {
            "asin": "NEAR-SIZE",
            "name": "Ceramic leak proof travel mug",
            "category": "travel mugs",
            "product_category": "Home › Kitchen › Travel Mugs",
            "Attributes": ["ceramic", "leak proof"],
            "options": {"color": ["red"], "size": ["medium"]},
            "pricing": [22.0],
        },
        {
            "asin": "TOO-MANY-FAILS",
            "name": "Plastic bottle",
            "category": "water bottles",
            "product_category": "Sports › Water Bottles",
            "Attributes": ["plastic"],
            "options": {"color": ["blue"], "size": ["small"]},
            "pricing": [40.0],
        },
    ]


def test_selects_real_near_match_with_exactly_one_violation() -> None:
    constraints = parse_goal_constraints(goal())

    match = select_near_match(constraints, catalog(), seed=13)

    assert match.product_id == "NEAR-SIZE"
    assert match.violated_constraints == ["option:size"]
    assert match.product_id in {row["asin"] for row in catalog()}
    assert match.product_id not in constraints.valid_target_ids


def test_n1_preserves_goal_and_names_catalog_near_match() -> None:
    context = build_webshop_n1_context(goal(), catalog(), seed=13)

    assert context.clean_goal == goal()["instruction_text"]
    assert context.noisy_goal.startswith(context.clean_goal)
    assert "NEAR-SIZE" in context.noisy_goal
    assert context.violated_constraint == "option:size"


def test_n2_is_order_overlay_and_retains_valid_target_top10() -> None:
    ranking = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "TARGET", "NEAR-SIZE"]

    overlay = build_webshop_n2_overlay(goal(), catalog(), ranking, seed=13)

    assert overlay.promoted_product_id == "NEAR-SIZE"
    assert overlay.output_product_ids.index("NEAR-SIZE") < 5
    assert overlay.output_product_ids.index("TARGET") < 10
    assert overlay.input_product_ids == ranking
    assert sorted(overlay.output_product_ids) == sorted(ranking)
    assert overlay.original_positions["NEAR-SIZE"] == 10


def test_webshop_static_noise_is_deterministic() -> None:
    first = build_webshop_n1_context(goal(), catalog(), seed=13)
    second = build_webshop_n1_context(goal(), catalog(), seed=13)
    assert first == second


def test_structural_calibration_prefers_retrievable_low_complexity_goals() -> None:
    goals = {
        1: {"asin": "A", "attributes": ["x", "y"], "goal_options": {}},
        2: {
            "asin": "B",
            "attributes": ["x"],
            "goal_options": {"size": "large"},
        },
        3: {"asin": "C", "attributes": ["x"], "goal_options": {}},
        4: {"asin": "D", "attributes": [], "goal_options": {}},
    }
    rankings = {
        1: ["Z", "A"],
        2: ["B"],
        3: ["Z"] * 10 + ["C"],
        4: ["Z", "D"],
    }

    selected = select_structurally_calibrated_goals(
        goals, rankings, count=2, min_options=0
    )
    option_selected = select_structurally_calibrated_goals(
        goals, rankings, count=1, min_options=1
    )

    assert selected == [4, 1]
    assert option_selected == [2]
