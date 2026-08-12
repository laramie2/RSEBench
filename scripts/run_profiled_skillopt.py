#!/usr/bin/env python
"""Generate a validated noise manifest and run paired SkillOpt evolution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.generation import generate_evolution_pairs_from_profile  # noqa: E402
from scripts.run_paired_skillopt import run_manifest  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--train-limit", type=int)
    parser.add_argument("--validation-limit", type=int)
    parser.add_argument("--test-limit", type=int)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = yaml.safe_load(args.profile.read_text(encoding="utf-8"))
    sizes = dict(config.get("sizes") or {})
    generation = generate_evolution_pairs_from_profile(
        args.profile, offline=args.offline
    )
    if generation.pair_manifest is None or generation.pair_manifest_path is None:
        detail = "; ".join(generation.errors) or generation.status
        raise RuntimeError(f"noise generation did not validate: {detail}")
    run_args = argparse.Namespace(
        manifest=Path(generation.pair_manifest_path),
        output_root=args.output_root,
        train_limit=args.train_limit or int(sizes["train"]),
        validation_limit=args.validation_limit or int(sizes["validation"]),
        test_limit=args.test_limit or int(sizes["clean_test"]),
        max_steps=args.max_steps,
        batch_size=args.batch_size,
        workers=args.workers,
        max_turns=args.max_turns,
        seed=args.seed,
    )
    run_dir = run_manifest(run_args)
    print(generation.run_dir)
    print(run_dir)


if __name__ == "__main__":
    main()
