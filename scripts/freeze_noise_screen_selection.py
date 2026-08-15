#!/usr/bin/env python3
"""Freeze a provider-free, portable noise-screen selection release."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = PROJECT_ROOT / "src"
for source in reversed((PROJECT_SRC, PROJECT_ROOT)):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from rsebench.selection.release import (  # noqa: E402
    freeze_selection_release_roots,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-root", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--release-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    frozen = freeze_selection_release_roots(
        selection_root=args.selection_root,
        run_root=args.run_root,
        destination=args.release_root,
    )
    print(f"release_id={frozen.release_id} provider_calls=0")
    print(frozen.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
