#!/usr/bin/env python3
"""Export deterministic WebShop Core-1 tasks and static overlays.

Run this script with WebShop's own Python environment. It imports the pinned
simulator, so the resulting goal indices exactly match SkillAdaptor at runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rsebench.core1.webshop import (
    build_webshop_n1_context,
    build_webshop_n2_overlay,
    select_structurally_calibrated_goals,
)
from web_agent_site.engine.engine import get_top_n_product_from_keywords
from web_agent_site.envs.web_agent_text_env import SimServer
from web_agent_site.utils import DEFAULT_FILE_PATH


SEED = 20260813


def ranked_ids(server: SimServer, query: str) -> list[str]:
    products = get_top_n_product_from_keywords(
        query.split(),
        server.search_engine,
        server.all_products,
        server.product_item_dict,
    )
    return [str(product["asin"]) for product in products]


def select_applicable(
    server: SimServer,
    candidates: range,
    count: int,
    *,
    min_options: int,
) -> list[int]:
    goals = {goal_idx: server.goals[goal_idx] for goal_idx in candidates}
    rankings = {
        goal_idx: ranked_ids(server, str(goal["query"]))
        for goal_idx, goal in goals.items()
    }
    eligible_count = sum(
        len(goal.get("goal_options") or {}) >= min_options
        and str(goal.get("asin") or "") in rankings[goal_idx][:10]
        for goal_idx, goal in goals.items()
    )
    ordered = select_structurally_calibrated_goals(
        goals,
        rankings,
        count=eligible_count,
        min_options=min_options,
    )
    selected: list[int] = []
    selected_queries: set[str] = set()
    for goal_idx in ordered:
        goal = server.goals[goal_idx]
        query = " ".join(str(goal.get("query") or "").casefold().split())
        if not query or query in selected_queries:
            continue
        try:
            build_webshop_n1_context(goal, server.all_products, SEED)
            build_webshop_n2_overlay(
                goal,
                server.all_products,
                rankings[goal_idx],
                SEED,
            )
        except ValueError:
            continue
        selected.append(goal_idx)
        selected_queries.add(query)
        if len(selected) == count:
            return selected
    raise RuntimeError(
        f"found only {len(selected)} WebShop N1/N2-applicable goals; need {count}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation-candidate-count", type=int, default=3)
    args = parser.parse_args()
    server = SimServer(
        "http://127.0.0.1:3000",
        DEFAULT_FILE_PATH,
        num_products=1000,
        human_goals=0,
    )
    # Official WebShop convention: test 0:500, validation 500:1500,
    # evolution/training from 1500 onward.
    train = select_applicable(
        server, range(1500, len(server.goals)), 5, min_options=1
    )
    validation_candidates = select_applicable(
        server,
        range(500, 1500),
        args.validation_candidate_count,
        min_options=0,
    )
    validation = validation_candidates[:3]
    test_goals = {goal_idx: server.goals[goal_idx] for goal_idx in range(500)}
    test_rankings = {
        goal_idx: ranked_ids(server, str(goal["query"]))
        for goal_idx, goal in test_goals.items()
    }
    test = select_structurally_calibrated_goals(
        test_goals, test_rankings, count=10, min_options=0
    )
    selected = train + validation_candidates + test
    goals: dict[str, dict] = {}
    n1: dict[str, dict] = {}
    n2: dict[str, dict] = {}
    for goal_idx in selected:
        goal = server.goals[goal_idx]
        goals[str(goal_idx)] = goal
        if goal_idx not in test:
            n1[str(goal_idx)] = build_webshop_n1_context(
                goal, server.all_products, SEED
            ).model_dump(mode="json")
            n2[str(goal_idx)] = build_webshop_n2_overlay(
                goal,
                server.all_products,
                ranked_ids(server, str(goal["query"])),
                SEED,
            ).model_dump(mode="json")
    payload = {
        "schema_version": "rsebench.core1-webshop-source.v2",
        "seed": SEED,
        "selection_policy": {
            "name": "retrievable_low_complexity",
            "retrieval_cutoff": 10,
            "uses_model_outcomes": False,
            "train_min_options": 1,
        },
        "source_goal_count": len(server.goals),
        "source_product_count": len(server.all_products),
        "train": train,
        "validation": validation,
        "validation_candidates": validation_candidates,
        "test": test,
        "goals": goals,
        "N1": {"stage": "N1", "goals": n1},
        "N2": {"stage": "N2", "goals": n2},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
