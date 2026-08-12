#!/usr/bin/env python
"""Materialize deterministic, group-isolated split manifests for all pilots."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.pilot import SplitCounts, build_split_manifest  # noqa: E402


def _spreadsheet_items(data_root: Path) -> list[tuple[str, str]]:
    path = (
        data_root
        / "materialized/spreadsheetbench_verified/spreadsheetbench_verified_400/dataset.json"
    )
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [(str(row["id"]), str(row["id"])) for row in rows]


def _docvqa_items(data_root: Path) -> list[tuple[str, str]]:
    path = data_root / "materialized/docvqa_10pct/docvqa_534.parquet"
    frame = pd.read_parquet(path, columns=["questionId", "docId"])
    return [
        (str(row.questionId), str(row.docId))
        for row in frame.itertuples(index=False)
    ]


def _dapo_items(data_root: Path) -> list[tuple[str, str]]:
    path = data_root / "materialized/dapo_fixed_1000/dapo_fixed_1000.parquet"
    frame = pd.read_parquet(path, columns=["normalized_problem_hash"])
    return [
        (str(value), str(value)) for value in frame["normalized_problem_hash"]
    ]


def _officeqa_items(methods_root: Path) -> list[tuple[str, str]]:
    root = methods_root / "skillopt/data/officeqa_id_split"
    rows: list[dict] = []
    for partition in ("train", "val", "test"):
        rows.extend(
            json.loads((root / partition / "items.json").read_text(encoding="utf-8"))
        )
    return [
        (
            str(row.get("uid") or row["id"]),
            "\n".join(sorted(str(row.get("source_files", "")).splitlines())),
        )
        for row in rows
    ]


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    methods_root = Path(
        os.environ.get("RSEBENCH_METHODS_ROOT", PROJECT_ROOT / "methods/external")
    )
    specs = yaml.safe_load(
        (PROJECT_ROOT / "benchmark/registry/splits.yaml").read_text(encoding="utf-8")
    )["splits"]
    loaders = {
        "spreadsheetbench_verified": lambda: _spreadsheet_items(data_root),
        "officeqa_full": lambda: _officeqa_items(methods_root),
        "docvqa_10pct": lambda: _docvqa_items(data_root),
        "dapo_fixed_1000": lambda: _dapo_items(data_root),
    }
    for benchmark, loader in loaders.items():
        row = specs[benchmark]
        counts = SplitCounts(
            **{
                name: row[name]
                for name in (
                    "total",
                    "evolution",
                    "pilot_evolve",
                    "pilot_eval",
                    "validation",
                    "test",
                )
            }
        )
        manifest = build_split_manifest(
            benchmark=benchmark,
            items=loader(),
            counts=counts,
            seed=20260812,
        )
        output = data_root / "splits" / benchmark / "split_manifest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(
            f"{benchmark}\tevolution={len(manifest.evolution)}"
            f"\tvalidation={len(manifest.validation)}\ttest={len(manifest.test)}\t{output}"
        )


if __name__ == "__main__":
    main()
