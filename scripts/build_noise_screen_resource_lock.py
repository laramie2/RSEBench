#!/usr/bin/env python3
"""Generate a verified, provider-free noise-screen resource lock."""

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

from rsebench.selection.resources import (  # noqa: E402
    build_resource_lock,
    validate_resource_lock_materializations,
    write_resource_lock,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--methods-root", required=True, type=Path)
    parser.add_argument("--methods-registry", required=True, type=Path)
    parser.add_argument("--image-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lock = build_resource_lock(
        selection_root=args.selection_root,
        data_root=args.data_root,
        methods_root=args.methods_root,
        methods_registry=args.methods_registry,
        image_manifest=args.image_manifest,
    )
    validate_resource_lock_materializations(
        lock,
        data_root=args.data_root,
        methods_root=args.methods_root,
        methods_registry=args.methods_registry,
        image_manifest=args.image_manifest,
    )
    write_resource_lock(args.output, lock)
    print(f"resources={len(lock.resources)} provider_calls=0")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
