#!/usr/bin/env python3
"""Repeatedly evaluate immutable SkillOpt artifacts without retraining."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = PROJECT_ROOT / "src"
for source in reversed((PROJECT_SRC, PROJECT_ROOT)):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from rsebench.core1.dataset import resolve_clean_split_paths  # noqa: E402
from rsebench.evolution.artifact_evaluation import (  # noqa: E402
    evaluate_repeated_artifacts,
)
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
)
from rsebench.evolution.skillopt_executor import (  # noqa: E402
    SkillOptBudget,
    SkillOptExecutor,
)
from rsebench.hashing import sha256_file  # noqa: E402
from scripts.baselines.common_env import (  # noqa: E402
    combined_method_env,
    methods_root,
)


ORDER_POLICY = "cyclic_rotation"


def parse_artifact_arguments(
    values: list[str], *, project_root: Path = PROJECT_ROOT
) -> dict[str, Path]:
    """Parse repeated ``LABEL=PATH`` arguments while preserving their order."""

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


def _task_manifest_hash(split: CleanEvolutionSplitManifest) -> str:
    payload = [task.model_dump(mode="json") for task in split.clean_test]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")  # type: ignore[union-attr]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = _parser().parse_args()
    if args.repeats < 2:
        raise ValueError("--repeats must be at least 2")
    if not args.dry_run and not args.confirm_provider_cost:
        raise ValueError("provider-backed replay requires --confirm-provider-cost")

    manifest = args.manifest.resolve()
    portable = CleanEvolutionSplitManifest.model_validate_json(
        manifest.read_text(encoding="utf-8")
    )
    environment = combined_method_env("skillopt")
    external_methods = methods_root()
    data_root = Path(environment["RSEBENCH_DATA_ROOT"])
    split = resolve_clean_split_paths(
        portable,
        project_root=PROJECT_ROOT,
        data_root=data_root,
        methods_root=external_methods,
    )
    artifacts = parse_artifact_arguments(args.artifact)
    if args.reference not in artifacts:
        raise ValueError(f"reference artifact is missing: {args.reference}")

    runtime = dict(split.metadata.get("runtime") or {})
    budget = SkillOptBudget(
        max_steps=int(runtime.get("max_steps", 3)),
        batch_size=int(runtime.get("batch_size", 4)),
        workers=int(runtime.get("workers", 2)),
        max_turns=int(runtime.get("max_tool_turns", 3)),
        max_completion_tokens=int(runtime.get("max_completion_tokens", 2048)),
    )
    output_dir = args.output_dir.resolve()
    previous_repeat_count = 0
    previous_result: dict[str, object] | None = None
    if args.resume:
        result_path = output_dir / "result.json"
        if not result_path.is_file():
            raise FileNotFoundError(f"replay result not found for resume: {result_path}")
        previous_result = json.loads(result_path.read_text(encoding="utf-8"))
        previous_repeat_count = int(previous_result["repeat_count"])  # type: ignore[arg-type]
        if args.repeats <= previous_repeat_count:
            raise ValueError("--repeats must exceed the existing repeat count")
    plan = {
        "schema_version": "rsebench.fixed-artifact-replay-plan.v1",
        "benchmark": split.benchmark,
        "domain": split.domain,
        "manifest": str(manifest),
        "split_source_hash": split.source_hash,
        "task_ids": [task.task_id for task in split.clean_test],
        "task_manifest_hash": _task_manifest_hash(split),
        "reference_label": args.reference,
        "repeat_count": args.repeats,
        "order_policy": ORDER_POLICY,
        "artifact_order": list(artifacts),
        "resume": args.resume,
        "previous_repeat_count": previous_repeat_count,
        "evaluation_count": args.repeats * len(artifacts),
        "additional_evaluation_count": (
            args.repeats - previous_repeat_count
        )
        * len(artifacts),
        "task_episode_count": args.repeats * len(artifacts) * len(split.clean_test),
        "additional_task_episode_count": (
            args.repeats - previous_repeat_count
        )
        * len(artifacts)
        * len(split.clean_test),
        "artifact_paths": {label: str(path) for label, path in artifacts.items()},
        "artifact_hashes": {label: sha256_file(path) for label, path in artifacts.items()},
        "runtime": runtime,
        "model": "deepseek-v4-flash",
        "temperature": 0.0,
        "thinking": "disabled",
        "provider_calls": 0 if args.dry_run else None,
    }

    if previous_result is not None:
        previous_order = previous_result.get("artifact_order") or [
            observation["artifact_label"]
            for observation in previous_result["observations"]  # type: ignore[index,union-attr]
            if observation["repeat"] == 1
        ]
        checks = {
            "artifact hashes": previous_result.get("artifact_hashes")
            == plan["artifact_hashes"],
            "artifact order": previous_order == plan["artifact_order"],
            "reference label": previous_result.get("reference_label")
            == plan["reference_label"],
            "task manifest hash": previous_result.get("task_manifest_hash")
            == plan["task_manifest_hash"],
            "task IDs": previous_result.get("task_ids") == plan["task_ids"],
            "order policy": previous_result.get("order_policy")
            == plan["order_policy"],
        }
        mismatches = [name for name, matches in checks.items() if not matches]
        if mismatches:
            raise ValueError(
                "resume preflight mismatch: " + ", ".join(mismatches)
            )

    if args.dry_run:
        if args.resume:
            plan_path = output_dir.with_name(f"{output_dir.name}.resume-plan.json")
        else:
            output_dir.mkdir(parents=True, exist_ok=False)
            plan_path = output_dir / "plan.json"
        _write_json(plan_path, plan)
        print(plan_path)
        print(json.dumps(plan, sort_keys=True))
        return

    _write_json(output_dir.with_name(f"{output_dir.name}.plan.json"), plan)
    executor = SkillOptExecutor(
        method_root=external_methods / "skillopt",
        data_root=data_root,
        environment=environment,
        budget=budget,
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
    _write_json(output_dir / "plan.json", plan)
    print(output_dir)
    print(
        json.dumps(
            {
                label: summary.model_dump(mode="json")
                for label, summary in result.summaries.items()
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
