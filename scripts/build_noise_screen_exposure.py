#!/usr/bin/env python3
"""Build a portable registry of historical benchmark task exposure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from rsebench.selection import (
    ExposureLevel,
    ExposureSource,
    build_exposure_registry,
)


def parse_source(value: str) -> ExposureSource:
    """Parse ``LABEL=PATH:LEVEL`` into a typed exposure source."""

    try:
        labeled_root, raw_level = value.rsplit(":", 1)
        label, raw_root = labeled_root.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "source must use LABEL=PATH:LEVEL syntax"
        ) from exc
    if not label or not raw_root:
        raise argparse.ArgumentTypeError("source label and path must be non-empty")
    try:
        level = ExposureLevel(raw_level)
    except ValueError as exc:
        choices = ", ".join(level.value for level in ExposureLevel)
        raise argparse.ArgumentTypeError(
            f"source level must be one of: {choices}"
        ) from exc
    return ExposureSource(label=label, root=Path(raw_root), level=level)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        type=parse_source,
        help="labeled source in LABEL=PATH:LEVEL form; repeat for each root",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_parent = args.output.resolve().parent
    excluded_roots = [
        output_parent
        for source in args.source
        if source.root.is_dir()
        and output_parent != source.root.resolve()
        and output_parent.is_relative_to(source.root.resolve())
    ]
    registry = build_exposure_registry(
        args.source,
        exclude_roots=excluded_roots,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            registry.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(registry.records)} exposure records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
