#!/usr/bin/env python
"""Audit exact observable token usage in legacy RSEBench artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.usage.backfill import audit_historical_usage  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Destination directory (default: PROJECT/outputs/legacy-token-audit)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_dir = args.output_dir or args.project_root / "outputs/legacy-token-audit"
    summary = audit_historical_usage(args.project_root, output_dir)
    print(output_dir / "summary.json")
    print(
        json.dumps(
            {
                "exact_lower_bound": summary["exact_lower_bound"],
                "observed_calls": summary["observed_calls"],
                "unobservable_calls": summary["unobservable_calls"],
                "billed_tokens": summary["billed_tokens"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
