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
from rsebench.experiments.bootstrap import patch_hashes_for_series  # noqa: E402
from scripts.build_core1_splits import _webshop_task  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "benchmark/validation/clean_qualification_v1"
DEFAULT_SOURCE = OUTPUT_ROOT / "webshop_source.json"
DEFAULT_SELECTION = OUTPUT_ROOT / "webshop_validation_selection.json"
DEFAULT_OUTPUT = OUTPUT_ROOT / "webshop.json"
V2_OUTPUT_ROOT = PROJECT_ROOT / "benchmark/validation/clean_qualification_v2"
V2_OUTPUT = V2_OUTPUT_ROOT / "webshop.json"
PATCH_SERIES = (
    PROJECT_ROOT / "patches/baselines/skilladaptor/series.yaml"
)


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


def build_clean_webshop_split_v2(
    *,
    source_path: Path = DEFAULT_SOURCE,
    selection_path: Path = DEFAULT_SELECTION,
) -> CleanEvolutionSplitManifest:
    """Preserve V1 sampling while pinning the repaired SkillAdaptor runtime."""

    v1 = build_clean_webshop_split(
        source_path=source_path,
        selection_path=selection_path,
    )
    metadata = json.loads(json.dumps(v1.metadata))
    calibration_baseline = metadata["validation_selection"]["baseline"]
    metadata.update(
        {
            "config_version": "clean-qualification-v2",
            "qualification_version": "clean-qualification-v2",
            "calibration_selection_path": (
                "rsebench-project://benchmark/validation/clean_qualification_v1/"
                "webshop_validation_selection.json"
            ),
            "runtime_baseline": {
                "name": "skilladaptor",
                "revision": calibration_baseline["revision"],
                "seed_skill_hash": calibration_baseline["seed_skill_hash"],
                "patch_hashes": patch_hashes_for_series(PATCH_SERIES),
            },
            "qualification_amendment": {
                "supersedes": "clean-qualification-v1",
                "sampling_changed": False,
                "repairs": [
                    "normalize_numeric_webshop_task_ids",
                    "fallback_to_available_navigation_after_bad_action_repair",
                    "skip_one_malformed_linker_attribution_candidate",
                ],
            },
        }
    )
    payload = {
        "benchmark": v1.benchmark,
        "domain": v1.domain,
        "seed": v1.seed,
        "train": [task.model_dump(mode="json") for task in v1.train],
        "validation": [task.model_dump(mode="json") for task in v1.validation],
        "clean_test": [task.model_dump(mode="json") for task in v1.clean_test],
        "metadata": metadata,
    }
    return v1.model_copy(
        update={"source_hash": canonical_hash(payload), "metadata": metadata}
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--qualification-version", choices=("v1", "v2"), default="v1"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.qualification_version == "v2":
        split = build_clean_webshop_split_v2(
            source_path=args.source,
            selection_path=args.selection,
        )
        output = args.output or V2_OUTPUT
    else:
        split = build_clean_webshop_split(
            source_path=args.source,
            selection_path=args.selection,
        )
        output = args.output or DEFAULT_OUTPUT
    encoded = (split.model_dump_json(indent=2) + "\n").encode("utf-8")
    if output.exists() and output.read_bytes() != encoded:
        raise FileExistsError(f"different clean manifest already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    print(output)


if __name__ == "__main__":
    main()
