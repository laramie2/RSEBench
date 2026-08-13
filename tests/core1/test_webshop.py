from __future__ import annotations

from rsebench.core1.webshop import (
    build_webshop_n1_context,
    build_webshop_n2_overlay,
    parse_goal_constraints,
    select_near_match,
)


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
