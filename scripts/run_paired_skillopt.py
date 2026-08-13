#!/usr/bin/env python
"""Run one bounded clean/noisy SkillOpt self-evolution comparison."""

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
from rsebench.evolution.skillopt_executor import (  # noqa: E402
    SkillOptBudget,
    SkillOptExecutor,
)
from scripts.baselines.common_env import combined_method_env, methods_root  # noqa: E402


_SEEDS = {
    "spreadsheetbench_verified": "skillopt/envs/spreadsheetbench/skills/initial.md",
    "officeqa_full": "skillopt/envs/officeqa/skills/initial.md",
    "livemathematicianbench": "skillopt/envs/livemathematicianbench/skills/initial.md",
    "dapo_fixed_1000": "skillopt/envs/dapo/skills/initial.md",
    "docvqa_10pct": "skillopt/envs/docvqa/skills/initial.md",
    "searchqa_skillopt": "skillopt/envs/searchqa/skills/initial.md",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--train-limit", type=int, default=3)
    parser.add_argument("--validation-limit", type=int, default=1)
    parser.add_argument("--test-limit", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--max-completion-tokens", type=int, default=2048)
    parser.add_argument("--stage", choices=["N1", "N2", "N3", "N4"])
    parser.add_argument("--seed", type=int, default=20260812)
    return parser.parse_args()


def run_manifest(args: argparse.Namespace) -> Path:
    """Execute one paired SkillOpt manifest and return its run directory."""

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
    if not subset.train or not subset.clean_test:
        raise ValueError("paired run needs non-empty train and clean test splits")
    environment = combined_method_env("skillopt")
    method_root = methods_root() / "skillopt"
    data_root = Path(environment["RSEBENCH_DATA_ROOT"])
    output_root = args.output_root or Path(
        environment.get("RSEBENCH_OUTPUT_ROOT", str(PROJECT_ROOT / "outputs"))
    ) / "runs/paired-evolution"
    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=data_root,
        environment=environment,
        budget=SkillOptBudget(
            max_steps=args.max_steps,
            batch_size=args.batch_size,
            workers=args.workers,
            max_turns=args.max_turns,
            max_completion_tokens=args.max_completion_tokens,
        ),
    )
    seed_skill = method_root / _SEEDS[subset.benchmark]
    parameters = {
        "model": "deepseek-v4-flash",
        "thinking": "disabled",
        "train_tasks": len(subset.train),
        "validation_tasks": len(subset.validation),
        "clean_test_tasks": len(subset.clean_test),
        "max_steps": args.max_steps,
        "batch_size": args.batch_size,
        "workers": args.workers,
        "max_turns": args.max_turns,
        "max_completion_tokens": args.max_completion_tokens,
        "stage": args.stage,
    }
    result = PairedEvolutionRunner(executor).run(
        method="skillopt",
        split=subset,
        seed_skill_path=seed_skill,
        method_seed=args.seed,
        parameters=parameters,
        output_root=output_root,
    )
    return Path(result.run_dir)


def main() -> None:
    run_dir = run_manifest(_parse_args())
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    print(run_dir)
    print(json.dumps(result["metrics"], sort_keys=True))


if __name__ == "__main__":
    main()
