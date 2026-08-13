#!/usr/bin/env python3
"""Materialize one or all Core-1 runtime/profile artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from rsebench.core1.materialize import materialize_core1_profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", nargs="*", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("benchmark/core1"))
    args = parser.parse_args()
    profiles = args.profiles or sorted(Path("configs/core1").glob("*/*.yaml"))
    for profile in profiles:
        print(materialize_core1_profile(profile, output_root=args.output_root))


if __name__ == "__main__":
    main()

