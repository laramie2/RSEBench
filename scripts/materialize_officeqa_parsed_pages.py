#!/usr/bin/env python
"""Download and materialize OfficeQA oracle parsed pages without logging tokens."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import snapshot_download

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.domains.officeqa_materialization import (  # noqa: E402
    build_parsed_page_index,
    materialize_referenced_parsed_pages,
)
from scripts.baselines.common_env import _credential_env_path  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    load_dotenv(_credential_env_path())
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise RuntimeError("HF_TOKEN is empty")
    data_root = args.data_root or Path(
        os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data")
    )
    raw_root = data_root / "raw/officeqa"
    snapshot_download(
        repo_id="databricks/officeqa",
        repo_type="dataset",
        allow_patterns="treasury_bulletins_parsed/jsons/*.json",
        token=token,
        local_dir=raw_root,
    )
    dataset = data_root / "materialized/officeqa_full/officeqa_full.csv"
    rows = pd.read_csv(dataset).to_dict(orient="records")
    destination = data_root / "materialized/officeqa_full/parsed"
    paths = materialize_referenced_parsed_pages(
        rows,
        raw_root=raw_root,
        destination_root=destination,
    )
    index = build_parsed_page_index(paths, destination)
    (destination / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"materialized {len(paths)} OfficeQA parsed JSON files")
    print(destination / "index.json")


if __name__ == "__main__":
    main()
