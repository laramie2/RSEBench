#!/usr/bin/env python
"""Materialize deterministic, group-isolated split manifests for all pilots."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

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


def _livemath_items(data_root: Path) -> list[tuple[str, str]]:
    root = data_root / "raw/live_mathematician_bench/data"
    items: list[tuple[str, str]] = []
    for path in sorted(root.glob("*/qa_*_final.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            task_id = f"{row.get('month')}:{row.get('no')}"
            items.append((task_id, str(row.get("paper_link") or task_id)))
    return items


def _officeqa_connected_items(rows: Iterable[dict]) -> list[tuple[str, str]]:
    materialized = list(rows)
    parent = {
        str(row.get("uid") or row["id"]): str(row.get("uid") or row["id"])
        for row in materialized
    }

    def find(task_id: str) -> str:
        while parent[task_id] != task_id:
            parent[task_id] = parent[parent[task_id]]
            task_id = parent[task_id]
        return task_id

    def union(first: str, second: str) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    source_owners: dict[str, list[str]] = defaultdict(list)
    for row in materialized:
        task_id = str(row.get("uid") or row["id"])
        for source in str(row.get("source_files", "")).splitlines():
            if source := source.strip():
                source_owners[source].append(task_id)
    for task_ids in source_owners.values():
        for task_id in task_ids[1:]:
            union(task_ids[0], task_id)

    components: dict[str, list[str]] = defaultdict(list)
    for task_id in parent:
        components[find(task_id)].append(task_id)
    group_by_task = {
        task_id: min(task_ids)
        for task_ids in components.values()
        for task_id in task_ids
    }
    return [(task_id, group_by_task[task_id]) for task_id in sorted(parent)]


def _officeqa_items(data_root: Path) -> list[tuple[str, str]]:
    path = data_root / "materialized/officeqa_full/officeqa_full.csv"
    frame = pd.read_csv(path, usecols=["uid", "source_files"])
    return _officeqa_connected_items(frame.to_dict(orient="records"))


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    specs = yaml.safe_load(
        (PROJECT_ROOT / "benchmark/registry/splits.yaml").read_text(encoding="utf-8")
    )["splits"]
    loaders = {
        "spreadsheetbench_verified": lambda: _spreadsheet_items(data_root),
        "officeqa_full": lambda: _officeqa_items(data_root),
        "docvqa_10pct": lambda: _docvqa_items(data_root),
        "dapo_fixed_1000": lambda: _dapo_items(data_root),
        "livemathematicianbench": lambda: _livemath_items(data_root),
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
