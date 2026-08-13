#!/usr/bin/env python3
"""Run one budget-locked clean SkillOpt baseline qualification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.core1.dataset import resolve_clean_split_paths  # noqa: E402
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
)
from rsebench.evolution.clean_runner import CleanEvolutionRunner  # noqa: E402
from rsebench.evolution.skillopt_executor import (  # noqa: E402
    SkillOptBudget,
    SkillOptExecutor,
)
from scripts.baselines.common_env import combined_method_env, methods_root  # noqa: E402


METHOD_SEEDS = (20260813, 20260814, 20260815)
_SEEDS = {
    "spreadsheetbench_verified": "skillopt/envs/spreadsheetbench/skills/initial.md",
    "officeqa_full": "skillopt/envs/officeqa/skills/initial.md",
}
EXPECTED = {
    "spreadsheetbench_verified": SkillOptBudget(
        max_steps=3,
        batch_size=7,
        workers=2,
        max_turns=3,
        max_completion_tokens=2048,
    ),
    "officeqa_full": SkillOptBudget(
        max_steps=3,
        batch_size=4,
        workers=2,
        max_turns=12,
        max_completion_tokens=4096,
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--method-seed", type=int, choices=METHOD_SEEDS, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def _runtime_payload(budget: SkillOptBudget) -> dict[str, int]:
    return {
        "max_steps": budget.max_steps,
        "batch_size": budget.batch_size,
        "workers": budget.workers,
        "max_tool_turns": budget.max_turns,
        "max_completion_tokens": budget.max_completion_tokens,
    }


def _policy(benchmark: str) -> CleanQualificationPolicy:
    if benchmark == "officeqa_full":
        return CleanQualificationPolicy(
            min_parseable_answer_rate=0.80,
            max_systemic_failure_rate=0.05,
        )
    return CleanQualificationPolicy()


def run_manifest(
    manifest: Path,
    *,
    method_seed: int,
    output_root: Path,
) -> Path:
    """Execute one formal clean SkillOpt manifest and return its run directory."""

    if method_seed not in METHOD_SEEDS:
        raise ValueError(f"unsupported formal method seed: {method_seed}")
    split = CleanEvolutionSplitManifest.model_validate_json(
        manifest.read_text(encoding="utf-8")
    )
    try:
        budget = EXPECTED[split.benchmark]
    except KeyError as exc:
        raise ValueError(
            f"unsupported clean SkillOpt benchmark: {split.benchmark}"
        ) from exc
    expected_runtime = _runtime_payload(budget)
    if split.metadata.get("runtime") != expected_runtime:
        raise ValueError(
            f"{split.benchmark} runtime metadata differs from formal settings"
        )

    environment = combined_method_env("skillopt")
    external_methods = methods_root()
    method_root = external_methods / "skillopt"
    data_root = Path(environment["RSEBENCH_DATA_ROOT"])
    split = resolve_clean_split_paths(
        split,
        project_root=PROJECT_ROOT,
        data_root=data_root,
        methods_root=external_methods,
    )
    seed_skill = external_methods / _SEEDS[split.benchmark]
    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=data_root,
        environment=environment,
        budget=budget,
    )
    parameters = {
        "qualification_version": "clean-qualification-v1",
        "model": "deepseek-v4-flash",
        "thinking": "disabled",
        "temperature": 0,
        "train_tasks": len(split.train),
        "validation_tasks": len(split.validation),
        "clean_test_tasks": len(split.clean_test),
        "runtime": expected_runtime,
    }
    result = CleanEvolutionRunner(executor).run(
        method="skillopt",
        split=split,
        seed_skill_path=seed_skill,
        method_seed=method_seed,
        parameters=parameters,
        output_root=Path(output_root) / split.benchmark / str(method_seed),
        policy=_policy(split.benchmark),
    )
    return Path(result.run_dir)


def main() -> None:
    args = build_parser().parse_args()
    run_dir = run_manifest(
        args.manifest,
        method_seed=args.method_seed,
        output_root=args.output_root,
    )
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    print(run_dir)
    print(json.dumps(result["qualification"], sort_keys=True))


if __name__ == "__main__":
    main()
