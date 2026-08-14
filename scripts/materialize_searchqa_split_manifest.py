#!/usr/bin/env python
"""Freeze RSEBench partitions over SkillOpt's released SearchQA ID split."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED = 20260812


def _ids(path: Path) -> list[str]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"expected JSON array: {path}")
    ids = [str(row.get("id") or "") for row in rows]
    if any(not task_id for task_id in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"SearchQA IDs are empty or duplicated: {path}")
    return ids


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    source = data_root / "materialized/searchqa_skillopt_split"
    evolution = _ids(source / "train/items.json")
    validation = _ids(source / "val/items.json")
    test = _ids(source / "test/items.json")
    if set(evolution) & set(validation) or set(evolution + validation) & set(test):
        raise ValueError("SearchQA source partitions overlap")
    assignments = {
        **{task_id: "evolution" for task_id in evolution},
        **{task_id: "validation" for task_id in validation},
        **{task_id: "test" for task_id in test},
    }
    manifest = {
        "benchmark": "searchqa_skillopt",
        "seed": SEED,
        "evolution": evolution,
        "pilot_evolve": evolution[:20],
        "pilot_eval": test[:10],
        "validation": validation,
        "test": test,
        "group_assignments": assignments,
    }
    output = data_root / "splits/searchqa_skillopt/split_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"output={output} evolution={len(evolution)} "
        f"validation={len(validation)} test={len(test)}"
    )


if __name__ == "__main__":
    main()
