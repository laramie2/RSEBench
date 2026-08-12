#!/usr/bin/env python
"""Download and materialize the RSE-Bench core pilot datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv

# The Xet transfer worker keeps a process-global error after a gated download is
# rejected. Standard HTTP is slower but makes independent dataset attempts truly
# independent and resumable.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
from huggingface_hub import snapshot_download


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DownloadItem:
    name: str
    source_id: str
    source_kind: str
    target: Path
    revision: str = "main"
    allow_patterns: tuple[str, ...] = ()
    materializer: str | None = None


def build_download_plan(data_root: Path) -> list[DownloadItem]:
    raw = data_root / "raw"
    return [
        DownloadItem(
            "spreadsheetbench_verified",
            "KAKA22/SpreadsheetBench",
            "huggingface",
            raw / "spreadsheetbench",
            allow_patterns=(
                "README.md",
                ".gitattributes",
                "spreadsheetbench_verified_400.tar.gz",
            ),
            materializer="spreadsheetbench",
        ),
        DownloadItem(
            "docvqa_10pct",
            "lmms-lab/DocVQA",
            "huggingface",
            raw / "docvqa",
            allow_patterns=("README.md", "DocVQA/validation-*.parquet"),
            materializer="docvqa",
        ),
        DownloadItem(
            "dapo_fixed_1000",
            "BytedTsinghua-SIA/DAPO-Math-17k",
            "huggingface",
            raw / "dapo_math_17k",
            materializer="dapo",
        ),
        DownloadItem(
            "live_mathematician_bench",
            "LiveMathematicianBench/LiveMathematicianBench",
            "huggingface",
            raw / "live_mathematician_bench",
        ),
        DownloadItem(
            "wikitablequestions",
            "https://github.com/ppasupat/WikiTableQuestions.git",
            "git",
            raw / "wikitablequestions",
            revision="master",
        ),
        DownloadItem(
            "aime_2026",
            "https://github.com/eth-sri/matharena.git",
            "git",
            raw / "matharena",
            revision="main",
        ),
        DownloadItem(
            "officeqa_code",
            "https://github.com/databricks/officeqa.git",
            "git",
            raw / "officeqa_code",
            revision="main",
        ),
        # Keep gated data last: a missing access grant should be reported, but
        # it must never prevent public benchmark sources from being downloaded.
        DownloadItem(
            "officeqa_full",
            "databricks/officeqa",
            "huggingface",
            raw / "officeqa",
            allow_patterns=(
                "README.md",
                "LICENSE-*",
                "NOTICE",
                "officeqa_full.csv",
                "officeqa_pro.csv",
                "treasury_bulletins_parsed/transformed/treasury_bulletins_transformed.zip",
            ),
            materializer="officeqa",
        ),
    ]


def _download_huggingface(item: DownloadItem, token: str | None) -> None:
    item.target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=item.source_id,
        repo_type="dataset",
        revision=item.revision,
        local_dir=item.target,
        allow_patterns=list(item.allow_patterns) or None,
        token=token or None,
    )


def _download_git(item: DownloadItem) -> None:
    if (item.target / ".git").is_dir():
        origin = subprocess.check_output(
            ["git", "-C", str(item.target), "remote", "get-url", "origin"],
            text=True,
        ).strip()
        if origin != item.source_id:
            raise RuntimeError(f"origin mismatch for {item.name}: {origin}")
        return
    if item.target.exists():
        raise RuntimeError(f"target exists and is not a Git checkout: {item.target}")
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            item.revision,
            item.source_id,
            str(item.target),
        ],
        check=True,
    )


def _safe_tar_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with tarfile.open(archive) as handle:
        for member in handle.getmembers():
            destination = (target / member.name).resolve()
            if root not in destination.parents and destination != root:
                raise ValueError(f"unsafe tar member: {member.name}")
        handle.extractall(target, filter="data")


def _safe_zip_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            destination = (target / member.filename).resolve()
            if root not in destination.parents and destination != root:
                raise ValueError(f"unsafe zip member: {member.filename}")
        handle.extractall(target)


def _prompt_text(value: object) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("content", ""))
    return str(value)


def _normalized_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_docvqa_ids(methods_root: Path) -> set[str]:
    split_root = methods_root / "skillopt" / "data" / "docvqa_id_split"
    ids: set[str] = set()
    for split in ("train", "val", "test"):
        path = split_root / split / "items.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        ids.update(str(row.get("questionId") or row.get("id")) for row in rows)
    return ids


def materialize(item: DownloadItem, data_root: Path, methods_root: Path) -> None:
    materialized = data_root / "materialized" / item.name
    materialized.mkdir(parents=True, exist_ok=True)
    if item.materializer == "spreadsheetbench":
        archive = item.target / "spreadsheetbench_verified_400.tar.gz"
        marker = materialized / ".complete"
        if not marker.exists():
            _safe_tar_extract(archive, materialized)
            marker.write_text("ok\n", encoding="utf-8")
    elif item.materializer == "officeqa":
        source_csv = item.target / "officeqa_full.csv"
        target_csv = materialized / "officeqa_full.csv"
        if not target_csv.exists():
            target_csv.write_bytes(source_csv.read_bytes())
        archive = (
            item.target
            / "treasury_bulletins_parsed/transformed/treasury_bulletins_transformed.zip"
        )
        marker = materialized / ".corpus_complete"
        if archive.exists() and not marker.exists():
            _safe_zip_extract(archive, materialized / "corpus")
            marker.write_text("ok\n", encoding="utf-8")
    elif item.materializer == "docvqa":
        output = materialized / "docvqa_534.parquet"
        if not output.exists():
            ids = _load_docvqa_ids(methods_root)
            frames = [
                pd.read_parquet(path)
                for path in sorted((item.target / "DocVQA").glob("validation-*.parquet"))
            ]
            frame = pd.concat(frames, ignore_index=True)
            key = "questionId" if "questionId" in frame.columns else "question_id"
            subset = frame[frame[key].astype(str).isin(ids)].copy()
            if len(subset) != len(ids):
                found = set(subset[key].astype(str))
                raise RuntimeError(
                    f"DocVQA ID materialization found {len(found)}/{len(ids)} rows"
                )
            subset.to_parquet(output, index=False)
    elif item.materializer == "dapo":
        output = materialized / "dapo_fixed_1000.parquet"
        if not output.exists():
            source = item.target / "data" / "dapo-math-17k.parquet"
            frame = pd.read_parquet(source)
            frame["normalized_problem_hash"] = frame["prompt"].map(
                lambda value: _normalized_hash(_prompt_text(value))
            )
            frame = frame.drop_duplicates("normalized_problem_hash")
            subset = frame.sort_values("normalized_problem_hash").head(1000)
            if len(subset) != 1000:
                raise RuntimeError(f"DAPO has only {len(subset)} unique rows")
            subset.to_parquet(output, index=False)


def execute_plan(items: Iterable[DownloadItem], data_root: Path) -> list[dict]:
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.environ.get("HF_TOKEN") or None
    methods_root = Path(
        os.environ.get(
            "RSEBENCH_METHODS_ROOT", PROJECT_ROOT / "methods" / "external"
        )
    )
    results: list[dict] = []
    for item in items:
        try:
            print(f"downloading {item.name} from {item.source_id}")
            if item.source_kind == "huggingface":
                _download_huggingface(item, token)
            else:
                _download_git(item)
            if item.materializer:
                materialize(item, data_root, methods_root)
            status = "materialized" if item.materializer else "downloaded"
            results.append({"name": item.name, "status": status})
        except Exception as exc:  # keep the complete audit even if one source fails
            results.append(
                {"name": item.name, "status": "failed", "error": str(exc)}
            )
            print(f"failed {item.name}: {exc}")
    audit_root = data_root / "audit"
    audit_root.mkdir(parents=True, exist_ok=True)
    (audit_root / "download-status.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="core", choices=["core"])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    data_root = Path(
        os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data")
    )
    plan = build_download_plan(data_root)
    if args.dry_run:
        for item in plan:
            print(f"{item.name}\t{item.source_kind}\t{item.source_id}\t{item.target}")
        return
    results = execute_plan(plan, data_root)
    if any(row["status"] == "failed" for row in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
