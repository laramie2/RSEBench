#!/usr/bin/env python
"""Run one bounded clean/noisy SkillAdaptor WebShop comparison."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evolution.contracts import EvolutionSplitManifest  # noqa: E402
from rsebench.evolution.runner import PairedEvolutionRunner  # noqa: E402
from rsebench.evolution.skilladaptor_executor import (  # noqa: E402
    SkillAdaptorBudget,
    SkillAdaptorExecutor,
)
from scripts.baselines.common_env import combined_method_env, methods_root  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seed-skill", type=Path, required=True)
    parser.add_argument("--stage", choices=["N1", "N2", "N3", "N4"], required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--train-limit", type=int, default=5)
    parser.add_argument("--validation-limit", type=int, default=3)
    parser.add_argument("--test-limit", type=int, default=10)
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--max-episode-steps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260813)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    split = EvolutionSplitManifest.model_validate_json(
        args.manifest.read_text(encoding="utf-8")
    )
    subset = split.model_copy(
        update={
            "train": split.train[: args.train_limit],
            "validation": split.validation[: args.validation_limit],
            "clean_test": split.clean_test[: args.test_limit],
        }
    )
    if subset.benchmark != "webshop" or not subset.train or not subset.clean_test:
        raise ValueError("SkillAdaptor paired run requires a nonempty WebShop split")
    environment = combined_method_env("skilladaptor")
    root = methods_root()
    output_root = args.output_root or Path(
        environment.get("RSEBENCH_OUTPUT_ROOT", str(PROJECT_ROOT / "outputs"))
    ) / "runs/paired-evolution"
    executor = SkillAdaptorExecutor(
        method_root=root / "skilladaptor/skill-adaptor",
        webshop_root=root / "webshop",
        project_root=PROJECT_ROOT,
        environment=environment,
        budget=SkillAdaptorBudget(
            max_iterations=args.max_iterations,
            max_episode_steps=args.max_episode_steps,
        ),
    )
    result = PairedEvolutionRunner(executor).run(
        method="skilladaptor",
        split=subset,
        seed_skill_path=args.seed_skill,
        method_seed=args.seed,
        parameters={
            "stage": args.stage,
            "model": "deepseek-v4-flash",
            "thinking": "disabled",
            "train_tasks": len(subset.train),
            "validation_tasks": len(subset.validation),
            "clean_test_tasks": len(subset.clean_test),
            "max_iterations": args.max_iterations,
            "max_episode_steps": args.max_episode_steps,
        },
        output_root=output_root,
    )
    print(result.run_dir)
    print(json.dumps(result.metrics.model_dump(mode="json"), sort_keys=True))


if __name__ == "__main__":
    main()
