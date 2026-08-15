#!/usr/bin/env python3
"""Plan or run the fixed-artifact replays used by clean selection."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAYERS = {
    "spreadsheetbench_verified": "scripts/replay_fixed_skillopt_artifacts.py",
    "officeqa_full": "scripts/replay_fixed_skillopt_artifacts.py",
    "webshop": "scripts/replay_fixed_skilladaptor_artifacts.py",
    "skilllearnbench": "scripts/replay_fixed_skilllearn_artifacts.py",
}


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return (
        candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
    ).resolve()


def build_commands(spec: Mapping[str, Any]) -> list[list[str]]:
    jobs = spec.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("replay spec requires a non-empty jobs list")
    commands: list[list[str]] = []
    for job in jobs:
        if not isinstance(job, Mapping):
            raise ValueError("replay job must be an object")
        benchmark = str(job.get("benchmark") or "")
        replayer = REPLAYERS.get(benchmark)
        if replayer is None:
            raise ValueError(f"unsupported replay benchmark: {benchmark}")
        artifacts = job.get("artifacts")
        if not isinstance(artifacts, Mapping) or not artifacts:
            raise ValueError(f"replay job lacks artifacts: {benchmark}")
        command = [
            sys.executable,
            str((PROJECT_ROOT / replayer).resolve()),
            "--manifest",
            str(_resolve(str(job["manifest"]))),
            "--reference",
            str(job.get("reference") or "seed"),
            "--repeats",
            str(int(job.get("repeats", 3))),
            "--output-dir",
            str(_resolve(str(job["output_dir"]))),
        ]
        if job.get("resume") is True:
            command.append("--resume")
        if benchmark == "skilllearnbench":
            family = str(job.get("family") or "")
            if not family:
                raise ValueError("SkillLearn replay job requires family")
            command.extend(["--family", family])
            image_manifest = job.get("image_manifest")
            if not image_manifest:
                raise ValueError("SkillLearn replay job requires image_manifest")
            command.extend(["--image-manifest", str(_resolve(str(image_manifest)))])
        for label, raw_path in artifacts.items():
            command.extend(["--artifact", f"{label}={_resolve(str(raw_path))}"])
        commands.append(command)
    return commands


def build_root_replay_plan(
    *,
    selection_root: Path,
    run_root: Path,
    evaluation_role: str,
    candidate_index: int | None,
    repeats: int,
    resume: bool,
) -> dict[str, Any]:
    """Discover root-owned replay jobs without executing a provider call."""

    from rsebench.selection.qualification_io import discover_replay_jobs

    jobs = discover_replay_jobs(
        selection_root=selection_root,
        run_root=run_root,
        evaluation_role=evaluation_role,
        candidate_index=candidate_index,
        repeats=repeats,
        resume=resume,
    )
    return {
        "schema_version": "rsebench.noise-screen-replay-matrix.v1",
        "selection_root": str(selection_root.resolve()),
        "run_root": str(run_root.resolve()),
        "evaluation_role": evaluation_role,
        "candidate_index": candidate_index,
        "repeats": repeats,
        "resume": resume,
        "jobs": jobs,
        "commands": [job["command"] for job in jobs],
        "provider_calls": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--selection-root", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument(
        "--evaluation-role",
        choices=("qualification_test", "screening_test"),
    )
    parser.add_argument("--candidate-index", type=int, choices=(1, 2, 3))
    parser.add_argument("--repeats", type=int, choices=(3, 5), default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-provider-cost", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.spec is not None:
        if any(
            value is not None
            for value in (args.selection_root, args.run_root, args.evaluation_role)
        ):
            raise ValueError("--spec cannot be combined with root replay arguments")
        if args.output is None:
            raise ValueError("synthetic --spec mode requires --output")
        payload = json.loads(args.spec.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("replay spec must be an object")
        commands = build_commands(payload)
        plan: dict[str, Any] = {
            "schema_version": "rsebench.noise-screen-replay-matrix.v1",
            "commands": commands,
            "provider_calls": 0,
        }
        output = args.output
    else:
        if args.selection_root is None or args.run_root is None:
            raise ValueError("root mode requires --selection-root and --run-root")
        if args.evaluation_role is None:
            raise ValueError("root mode requires --evaluation-role")
        plan = build_root_replay_plan(
            selection_root=args.selection_root,
            run_root=args.run_root,
            evaluation_role=args.evaluation_role,
            candidate_index=args.candidate_index,
            repeats=args.repeats,
            resume=args.resume,
        )
        commands = list(plan["commands"])
        candidate = args.candidate_index if args.candidate_index is not None else "all"
        output = args.output or (
            args.run_root
            / "replay_plans"
            / f"{args.evaluation_role}-candidate-{candidate}-r{args.repeats}.json"
        )
    if args.execute and not args.confirm_provider_cost:
        raise ValueError(
            "provider-backed replay matrix requires --confirm-provider-cost"
        )
    if args.execute:
        plan["provider_calls"] = None
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not args.execute:
        print(output)
        return
    for command in commands:
        subprocess.run([*command, "--confirm-provider-cost"], check=True)
    print(output)


if __name__ == "__main__":
    main()
