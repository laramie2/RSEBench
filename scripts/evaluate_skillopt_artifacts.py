#!/usr/bin/env python
"""Evaluate fixed paired-run SkillOpt artifacts on an expanded clean test."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evolution.artifact_evaluation import (  # noqa: E402
    evaluate_skill_artifacts,
    resolve_source_run_skills,
)
from rsebench.evolution.report import render_artifact_comparison  # noqa: E402
from rsebench.evolution.skillopt_executor import (  # noqa: E402
    SkillOptBudget,
    SkillOptExecutor,
)
from rsebench.generation import _load_evolution_tasks, _resolve_split_path  # noqa: E402
from scripts.baselines.common_env import combined_method_env, methods_root  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--test-limit", type=int, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--seed", type=int, default=20260812)
    return parser.parse_args()


def _canonical_task_manifest(tasks: list[object]) -> tuple[dict[str, object], str]:
    records = [task.model_dump(mode="json") for task in tasks]  # type: ignore[union-attr]
    encoded = json.dumps(
        records, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return {"sha256": digest, "count": len(records), "tasks": records}, digest


def main() -> None:
    args = _parse_args()
    if args.test_limit < 1:
        raise ValueError("--test-limit must be positive")
    config = yaml.safe_load(args.profile.read_text(encoding="utf-8"))
    environment = combined_method_env("skillopt")
    data_root = Path(environment.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    split_path = _resolve_split_path(config["split_manifest"], data_root)
    split_payload = json.loads(split_path.read_text(encoding="utf-8"))
    partition = str((config.get("partitions") or {}).get("clean_test", "test"))
    test_ids = [str(value) for value in split_payload[partition]][: args.test_limit]
    if len(test_ids) != args.test_limit:
        raise ValueError(f"partition {partition} is smaller than --test-limit")
    clean_test = _load_evolution_tasks(config, data_root, test_ids)
    skills = resolve_source_run_skills(args.source_run)

    root = args.output_root or Path(
        environment.get("RSEBENCH_OUTPUT_ROOT", str(PROJECT_ROOT / "outputs"))
    ) / "runs/expanded-evaluation"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = root / f"{stamp}-{config['benchmark']}-skillopt"
    executor = SkillOptExecutor(
        method_root=methods_root() / "skillopt",
        data_root=data_root,
        environment=environment,
        budget=SkillOptBudget(
            workers=args.workers,
            max_turns=args.max_turns,
        ),
    )
    result = evaluate_skill_artifacts(
        executor=executor,
        seed_skill=skills["seed"],
        clean_skill=skills["clean"],
        noisy_skill=skills["noisy"],
        clean_test=clean_test,
        output_dir=output_dir,
        bootstrap_seed=args.seed,
    )
    task_manifest, _ = _canonical_task_manifest(clean_test)
    task_manifest.update(
        {
            "profile": str(args.profile.resolve()),
            "source_run": str(args.source_run.resolve()),
            "split_manifest": str(split_path.resolve()),
            "partition": partition,
        }
    )
    (output_dir / "test_task_manifest.json").write_text(
        json.dumps(task_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        render_artifact_comparison(result), encoding="utf-8"
    )
    print(output_dir)
    print(json.dumps(result.metrics.model_dump(), sort_keys=True))
    print(json.dumps(result.transitions.model_dump(), sort_keys=True))


if __name__ == "__main__":
    main()
