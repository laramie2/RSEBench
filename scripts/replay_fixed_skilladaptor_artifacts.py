#!/usr/bin/env python3
"""Repeatedly evaluate immutable SkillAdaptor WebShop skill banks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = PROJECT_ROOT / "src"
for source in reversed((PROJECT_SRC, PROJECT_ROOT)):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.evolution.artifact_evaluation import (  # noqa: E402
    evaluate_repeated_artifacts,
)
from rsebench.evolution.skilladaptor_executor import (  # noqa: E402
    SkillAdaptorBudget,
    SkillAdaptorExecutor,
)
from rsebench.hashing import sha256_file  # noqa: E402
from rsebench.selection.clean_view import load_clean_runtime_view  # noqa: E402
from scripts.baselines.common_env import (  # noqa: E402
    combined_method_env,
    methods_root,
)


ORDER_POLICY = "cyclic_rotation"
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.0
THINKING = "disabled"
BUDGET = SkillAdaptorBudget(max_iterations=3, max_episode_steps=15)


def parse_artifact_arguments(
    values: list[str], *, project_root: Path = PROJECT_ROOT
) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        label = label.strip()
        raw_path = raw_path.strip()
        if not separator or not label or not raw_path:
            raise ValueError(f"artifact must use LABEL=PATH: {value}")
        if label in artifacts:
            raise ValueError(f"duplicate artifact label: {label}")
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"artifact {label} not found: {path}")
        artifacts[label] = path
    if not artifacts:
        raise ValueError("at least one --artifact is required")
    return artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--reference", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--confirm-provider-cost", action="store_true")
    return parser


def _write_json(path: Path, payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _plan_path(output_dir: Path, *, resume: bool) -> Path:
    suffix = ".resume-plan.json" if resume else ".plan.json"
    return output_dir.with_name(output_dir.name + suffix)


def _validate_resume_plan(output_dir: Path, plan: dict[str, Any]) -> int:
    result_path = output_dir / "result.json"
    original_plan_path = output_dir / "plan.json"
    if not result_path.is_file() or not original_plan_path.is_file():
        raise FileNotFoundError("replay resume requires result.json and plan.json")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    original = json.loads(original_plan_path.read_text(encoding="utf-8"))
    locked = (
        "benchmark",
        "domain",
        "split_source_hash",
        "task_manifest_hash",
        "task_ids",
        "reference_label",
        "artifact_order",
        "artifact_hashes",
        "runtime",
        "model",
        "temperature",
        "thinking",
    )
    mismatches = [field for field in locked if original.get(field) != plan.get(field)]
    if result.get("artifact_hashes") != plan["artifact_hashes"]:
        mismatches.append("result artifact_hashes")
    if mismatches:
        raise ValueError("resume preflight mismatch: " + ", ".join(mismatches))
    previous = int(result["repeat_count"])
    if int(plan["repeat_count"]) <= previous:
        raise ValueError("--repeats must exceed the existing repeat count")
    return previous


def main() -> None:
    args = _parser().parse_args()
    if args.repeats < 2:
        raise ValueError("--repeats must be at least 2")
    if not args.dry_run and not args.confirm_provider_cost:
        raise ValueError("provider-backed replay requires --confirm-provider-cost")
    manifest = args.manifest.resolve()
    split = load_clean_runtime_view(manifest)
    if split.benchmark != "webshop" or split.domain != "interactive":
        raise ValueError("SkillAdaptor replay only supports WebShop")
    if len(split.clean_test) != 20:
        raise ValueError("WebShop fixed replay requires exactly 20 tasks")
    runtime = split.metadata.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("max_episode_steps") != 15:
        raise ValueError("WebShop fixed replay requires a 15-step runtime")
    artifacts = parse_artifact_arguments(args.artifact)
    if args.reference not in artifacts:
        raise ValueError(f"reference artifact is missing: {args.reference}")
    output_dir = args.output_dir.resolve()
    task_ids = [task.task_id for task in split.clean_test]
    plan: dict[str, Any] = {
        "schema_version": "rsebench.fixed-artifact-replay-plan.v1",
        "benchmark": split.benchmark,
        "domain": split.domain,
        "manifest": str(manifest),
        "split_source_hash": split.source_hash,
        "task_ids": task_ids,
        "task_manifest_hash": canonical_hash(
            [task.model_dump(mode="json") for task in split.clean_test]
        ),
        "reference_label": args.reference,
        "repeat_count": args.repeats,
        "order_policy": ORDER_POLICY,
        "artifact_order": list(artifacts),
        "artifact_paths": {label: str(path) for label, path in artifacts.items()},
        "artifact_hashes": {
            label: sha256_file(path) for label, path in artifacts.items()
        },
        "runtime": runtime,
        "model": MODEL,
        "temperature": TEMPERATURE,
        "thinking": THINKING,
        "provider_calls": 0 if args.dry_run else None,
    }
    previous = _validate_resume_plan(output_dir, plan) if args.resume else 0
    plan["resume"] = args.resume
    plan["previous_repeat_count"] = previous
    plan["additional_task_episode_count"] = (
        (args.repeats - previous) * len(artifacts) * len(task_ids)
    )
    plan_path = _plan_path(output_dir, resume=args.resume)
    if args.dry_run:
        _write_json(plan_path, plan)
        print(plan_path)
        return
    _write_json(plan_path, plan)
    external_methods = methods_root()
    executor = SkillAdaptorExecutor(
        method_root=external_methods / "skilladaptor/skill-adaptor",
        webshop_root=external_methods / "webshop",
        project_root=PROJECT_ROOT,
        budget=BUDGET,
        environment=combined_method_env("skilladaptor"),
    )
    result = evaluate_repeated_artifacts(
        executor=executor,
        artifacts=artifacts,
        reference_label=args.reference,
        clean_test=split.clean_test,
        repeats=args.repeats,
        output_dir=output_dir,
        resume=args.resume,
    )
    if not args.resume:
        _write_json(output_dir / "plan.json", plan)
    print(output_dir)
    print(json.dumps(result.summaries, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
