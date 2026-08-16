#!/usr/bin/env python3
"""Run the preregistered SkillFlow clean control plane."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rsebench.skillflow.contracts import (  # noqa: E402
    SkillFlowCleanConfig,
    SkillFlowInputManifest,
)
from rsebench.skillflow.runner import (  # noqa: E402
    aggregate_results,
    execute_attempt,
    freeze_qualified,
    plan_attempt,
    run_preflight,
    select_batch_b_families,
    select_confirmation_families,
    validate_provider_cost,
)


DEFAULT_CONFIG = "configs/experiments/skillflow-clean-qualification-v1.yaml"
DEFAULT_MANIFEST = (
    "benchmark/validation/skillflow_clean_qualification_v1/input_manifest.json"
)
DEFAULT_FREEZE = "benchmark/validation/skillflow_clean_qualification_v1/manifest.json"


def _shared_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--config", type=Path, default=Path(DEFAULT_CONFIG))
    parser.add_argument("--manifest", type=Path, default=Path(DEFAULT_MANIFEST))
    parser.add_argument("--method-root", type=Path, default=Path("methods/external/skillflow"))
    parser.add_argument("--output-root", type=Path, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight", help="run zero-provider readiness checks")
    _shared_arguments(preflight)
    for name in ("screen", "confirm"):
        paid = subparsers.add_parser(name, help=f"run paid SkillFlow {name} arms")
        _shared_arguments(paid)
        paid.add_argument("--attempt-id", default=None)
        paid.add_argument("--dry-run", action="store_true")
        paid.add_argument("--confirm-provider-cost", action="store_true")
        if name == "screen":
            paid.add_argument("--batch", choices=("a", "b"), default="a")
        if name == "confirm":
            paid.add_argument("--family", action="append", dest="families")
    aggregate = subparsers.add_parser("aggregate", help="aggregate all paired evidence")
    _shared_arguments(aggregate)
    freeze = subparsers.add_parser("freeze", help="freeze two qualified families")
    _shared_arguments(freeze)
    freeze.add_argument("--freeze-output", type=Path, default=Path(DEFAULT_FREEZE))
    return parser


def _resolve(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _load(args: argparse.Namespace) -> tuple[Path, Path, Path, SkillFlowCleanConfig, SkillFlowInputManifest]:
    project = args.project_root.resolve()
    config_path = _resolve(project, args.config)
    manifest_path = _resolve(project, args.manifest)
    config = SkillFlowCleanConfig.model_validate(
        yaml.safe_load(config_path.read_text(encoding="utf-8"))
    )
    manifest = SkillFlowInputManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    method_root = _resolve(project, args.method_root)
    configured_output = Path(config.output_root)
    output_root = (
        _resolve(project, args.output_root)
        if args.output_root is not None
        else _resolve(project, configured_output)
    )
    return project, method_root, output_root, config, manifest


def _attempt_id(phase: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{phase}-{stamp}"


def _print(payload: object) -> None:
    def encode(value: object) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"cannot serialize {type(value).__name__}")

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=encode,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project, method_root, output_root, config, manifest = _load(args)
    data_root = _resolve(project, Path(config.data_root))

    if args.command == "preflight":
        report = run_preflight(
            project_root=project,
            method_root=method_root,
            config=config,
            manifest=manifest,
            output_root=output_root,
        )
        output_root.mkdir(parents=True, exist_ok=True)
        path = output_root / "preflight.json"
        path.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _print(report)
        return 0 if report.status == "ready" else 2

    if args.command in {"screen", "confirm"}:
        validate_provider_cost(
            dry_run=args.dry_run,
            confirm_provider_cost=args.confirm_provider_cost,
        )
        selected = None
        missing_replicates = None
        if args.command == "screen" and args.batch == "b":
            current = aggregate_results(output_root=output_root, manifest=manifest)
            selected = select_batch_b_families(current, manifest)
        if args.command == "confirm":
            aggregate = aggregate_results(output_root=output_root, manifest=manifest)
            selected = select_confirmation_families(
                aggregate, manifest, args.families
            )
            aggregate_by_family = {
                family.family: family for family in aggregate.families
            }
            missing_replicates = {}
            for family in selected:
                existing = {
                    item.replicate_id
                    for item in aggregate_by_family[family].replicates
                }
                missing_replicates[family] = [
                    replicate_id
                    for replicate_id in ("r2", "r3")
                    if replicate_id not in existing
                ]
        if not args.dry_run:
            report = run_preflight(
                project_root=project,
                method_root=method_root,
                config=config,
                manifest=manifest,
                output_root=output_root,
            )
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "preflight.json").write_text(
                json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if report.status != "ready":
                _print(report)
                return 2
        attempt = plan_attempt(
            phase=args.command,
            attempt_id=args.attempt_id or _attempt_id(args.command),
            project_root=project,
            method_root=method_root,
            output_root=output_root,
            config=config,
            manifest=manifest,
            dry_run=args.dry_run,
            selected_families=selected,
            missing_replicates=missing_replicates,
        )
        results = execute_attempt(attempt, config=config, manifest=manifest)
        _print({"attempt": attempt, "paired_results": results})
        return 0

    aggregate = aggregate_results(output_root=output_root, manifest=manifest)
    if args.command == "aggregate":
        _print(aggregate)
        return 0
    freeze_path = _resolve(project, args.freeze_output)
    frozen = freeze_qualified(
        aggregate=aggregate,
        manifest=manifest,
        data_root=data_root,
        output_path=freeze_path,
    )
    _print(frozen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
