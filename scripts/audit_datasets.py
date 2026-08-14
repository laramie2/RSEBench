#!/usr/bin/env python
"""Create a non-mutating inventory of downloaded dataset snapshots."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
import pyarrow.parquet as pq
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.download.datasets import build_download_plan  # noqa: E402


def _bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return int(subprocess.check_output(["du", "-sb", str(path)], text=True).split()[0])


def _file_count(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hf_revision(path: Path) -> str | None:
    trees = path / ".cache" / "huggingface" / "trees"
    revisions = sorted(candidate.stem for candidate in trees.glob("*.json"))
    return revisions[-1] if revisions else None


def _inspect_materialized(name: str, materialized: Path) -> dict:
    if name == "spreadsheetbench_verified":
        dataset = materialized / "spreadsheetbench_verified_400" / "dataset.json"
        if dataset.is_file():
            payload = json.loads(dataset.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("data", [])
            return {
                "row_count": len(rows),
                "fields": sorted(rows[0]) if rows else [],
                "primary_sha256": _sha256(dataset),
            }
    parquet_names = {
        "docvqa_10pct": "docvqa_534.parquet",
        "dapo_fixed_1000": "dapo_fixed_1000.parquet",
    }
    if name in parquet_names:
        dataset = materialized / parquet_names[name]
        if dataset.is_file():
            metadata = pq.ParquetFile(dataset)
            return {
                "row_count": metadata.metadata.num_rows,
                "fields": metadata.schema.names,
                "primary_sha256": _sha256(dataset),
            }
    if name == "officeqa_full":
        dataset = materialized / "officeqa_full.csv"
        if dataset.is_file():
            import pandas as pd

            frame = pd.read_csv(dataset)
            return {
                "row_count": len(frame),
                "fields": list(frame.columns),
                "primary_sha256": _sha256(dataset),
            }
    return {"row_count": None, "fields": [], "primary_sha256": None}


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    output_root = Path(
        os.environ.get("RSEBENCH_OUTPUT_ROOT", PROJECT_ROOT / "outputs")
    )
    status_path = data_root / "audit" / "download-status.json"
    statuses = (
        {row["name"]: row for row in json.loads(status_path.read_text())}
        if status_path.exists()
        else {}
    )
    inventory_path = PROJECT_ROOT / "benchmark" / "registry" / "data_inventory.yaml"
    inventory = (
        yaml.safe_load(inventory_path.read_text(encoding="utf-8")).get("artifacts", {})
        if inventory_path.exists()
        else {}
    )
    rows = {}
    for item in build_download_plan(data_root):
        materialized = data_root / "materialized" / item.name
        source_status = statuses.get(item.name, {})
        status = source_status.get("status", "missing")
        detail = source_status.get("error")
        if status == "failed" and detail and (
            "restricted" in detail.lower() or "not in the authorized list" in detail.lower()
        ):
            status = "blocked_access"
        row = {
            "source_id": item.source_id,
            "source_kind": item.source_kind,
            "revision": item.revision,
            "raw_path": str(item.target),
            "raw_bytes": _bytes(item.target),
            "raw_files": _file_count(item.target),
            "materialized_path": str(materialized),
            "materialized_bytes": _bytes(materialized),
            "materialized_files": _file_count(materialized),
            "status": status,
            "status_detail": detail,
            "license_review": inventory.get(item.name, {}).get(
                "license_review", "unregistered"
            ),
            **_inspect_materialized(item.name, materialized),
        }
        if item.source_kind == "huggingface":
            row["resolved_revision"] = _hf_revision(item.target)
        if item.source_kind == "git" and (item.target / ".git").is_dir():
            row["resolved_revision"] = subprocess.check_output(
                ["git", "-C", str(item.target), "rev-parse", "HEAD"], text=True
            ).strip()
        rows[item.name] = row
    output = output_root / "audits" / "datasets.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print(output)
    for name, row in rows.items():
        print(
            f"{name}\tstatus={row['status']}\traw_bytes={row['raw_bytes']}"
            f"\tmaterialized_bytes={row['materialized_bytes']}"
        )


if __name__ == "__main__":
    main()
