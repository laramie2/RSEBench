#!/usr/bin/env python3
"""Freeze the clean-only 5/5/20 WebShop qualification manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
)
from scripts.build_core1_splits import _webshop_task  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "benchmark/validation/clean_qualification_v1"
DEFAULT_SOURCE = OUTPUT_ROOT / "webshop_source.json"
DEFAULT_SELECTION = OUTPUT_ROOT / "webshop_validation_selection.json"
DEFAULT_OUTPUT = OUTPUT_ROOT / "webshop.json"


def build_clean_webshop_split(
    *,
    source_path: Path = DEFAULT_SOURCE,
    selection_path: Path = DEFAULT_SELECTION,
) -> CleanEvolutionSplitManifest:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection.get("execution_failures"):
        raise RuntimeError("cannot freeze WebShop split with execution failures")
    if selection.get("uses_evolved_outcomes") is not False:
        raise ValueError("WebShop validation selection must not use evolved outcomes")
    if selection.get("uses_clean_test_outcomes") is not False:
        raise ValueError("WebShop validation selection must not use clean-test outcomes")

    train_ids = [int(value) for value in source["train"]]
    validation_ids = [int(value) for value in selection["selected_ids"]]
    test_ids = [int(value) for value in source["test"]]
    if (len(train_ids), len(validation_ids), len(test_ids)) != (5, 5, 20):
        raise ValueError("WebShop clean qualification requires exact 5/5/20 sizes")
    candidate_ids = {int(value) for value in source["validation_candidates"]}
    if not set(validation_ids).issubset(candidate_ids):
        raise ValueError("selected validation IDs must come from frozen candidates")

    goals = source["goals"]
    tasks = {
        goal_idx: _webshop_task(goal_idx, goals[str(goal_idx)])
        for goal_idx in train_ids + validation_ids + test_ids
    }
    metadata: dict[str, Any] = {
        "config_version": "clean-qualification-v1",
        "qualification_version": "clean-qualification-v1",
        "baseline": "skilladaptor",
        "source_partition": {
            "train": "official_train_1500_end",
            "validation": "official_validation_500_1500_seed_calibrated",
            "clean_test": "official_test_0_500",
        },
        "runtime": {
            "max_iterations": 3,
            "max_episode_steps": 15,
            "min_sample_size": 5,
        },
        "validation_selection": {
            "policy": selection["policy"],
            "selected_seed_score": selection["selected_seed_score"],
            "baseline": selection["baseline"],
        },
    }
    payload = {
        "benchmark": "webshop",
        "domain": "interactive",
        "seed": int(source["seed"]),
        "train": [tasks[value].model_dump(mode="json") for value in train_ids],
        "validation": [
            tasks[value].model_dump(mode="json") for value in validation_ids
        ],
        "clean_test": [tasks[value].model_dump(mode="json") for value in test_ids],
        "metadata": metadata,
    }
    return CleanEvolutionSplitManifest(
        benchmark="webshop",
        domain="interactive",
        seed=int(source["seed"]),
        source_hash=canonical_hash(payload),
        train=[tasks[value] for value in train_ids],
        validation=[tasks[value] for value in validation_ids],
        clean_test=[tasks[value] for value in test_ids],
        metadata=metadata,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    split = build_clean_webshop_split(
        source_path=args.source,
        selection_path=args.selection,
    )
    encoded = (split.model_dump_json(indent=2) + "\n").encode("utf-8")
    if args.output.exists() and args.output.read_bytes() != encoded:
        raise FileExistsError(f"different clean manifest already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(args.output)


if __name__ == "__main__":
    main()
