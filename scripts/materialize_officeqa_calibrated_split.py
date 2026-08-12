#!/usr/bin/env python
"""Freeze the calibrated OfficeQA 12/6/20 split after runtime selection."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evolution.calibration import (  # noqa: E402
    OfficeQACalibrationRun,
    freeze_officeqa_pilot,
)
from scripts.baselines.common_env import _credential_env_path  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration-result", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=20260812)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    calibration = OfficeQACalibrationRun.model_validate_json(
        args.calibration_result.read_text(encoding="utf-8")
    )
    if calibration.selected_runtime is None:
        raise RuntimeError("OfficeQA calibration has no selected runtime")
    load_dotenv(_credential_env_path())
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    rows = pd.read_csv(
        data_root / "materialized/officeqa_full/officeqa_full.csv"
    ).to_dict(orient="records")
    split = freeze_officeqa_pilot(rows, calibration.calibration_ids, seed=args.seed)
    output = args.output or data_root / "splits/officeqa_calibrated/split_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = split.model_dump_json(indent=2) + "\n"
    if output.exists():
        if output.read_text(encoding="utf-8") != serialized:
            raise FileExistsError(f"different calibrated split already exists: {output}")
    else:
        output.write_text(serialized, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
