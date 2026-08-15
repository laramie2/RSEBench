#!/usr/bin/env python3
"""Aggregate only filesystem-owned clean qualification evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = PROJECT_ROOT / "src"
for source in reversed((PROJECT_SRC, PROJECT_ROOT)):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


def aggregate_from_roots(
    *,
    selection_root: Path,
    run_root: Path,
    mode: str,
    clean_v2_root: Path | None = None,
    skillopt_replay_root: Path | None = None,
) -> Any:
    from rsebench.selection.qualification_io import aggregate_selection_roots

    return aggregate_selection_roots(
        selection_root=selection_root,
        run_root=run_root,
        mode=mode,
        clean_v2_root=clean_v2_root,
        skillopt_replay_root=skillopt_replay_root,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--clean-v2-root", type=Path)
    parser.add_argument("--skillopt-replay-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("reuse-audit", "qualification", "screening-generalization"),
        default="qualification",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_root = args.run_root or args.output.parent
    if args.mode != "reuse-audit" and args.run_root is None:
        raise ValueError(f"{args.mode} mode requires --run-root")
    output_payload = aggregate_from_roots(
        selection_root=args.selection_root,
        run_root=run_root,
        mode=args.mode,
        clean_v2_root=args.clean_v2_root,
        skillopt_replay_root=args.skillopt_replay_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output_payload.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
