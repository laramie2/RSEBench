#!/usr/bin/env python3
"""Plan or run the fixed-artifact replays used by clean selection."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--selection-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument(
        "--evaluation-role",
        choices=("qualification_test", "screening_test"),
        required=True,
    )
    parser.add_argument("--candidate-index", type=int, choices=(1, 2, 3))
    parser.add_argument("--repeats", type=int, choices=(3, 5), default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-provider-cost", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
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
