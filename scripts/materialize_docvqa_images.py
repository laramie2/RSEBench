#!/usr/bin/env python
"""Extract immutable DocVQA image bytes from the materialized parquet file."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    dataset = data_root / "materialized/docvqa_10pct/docvqa_534.parquet"
    output = data_root / "materialized/docvqa_10pct/images"
    output.mkdir(parents=True, exist_ok=True)
    frame = pd.read_parquet(dataset, columns=["questionId", "image"])
    records: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        task_id = str(row.questionId)
        image = row.image if isinstance(row.image, dict) else {}
        payload = image.get("bytes")
        if not isinstance(payload, bytes) or not payload:
            raise ValueError(f"DocVQA row {task_id} has no image bytes")
        target = output / f"{task_id}.png"
        if not target.exists() or target.read_bytes() != payload:
            target.write_bytes(payload)
        records.append({"task_id": task_id, "path": str(target.resolve()), "bytes": len(payload)})
    (output / "index.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"materialized={len(records)} output={output}")


if __name__ == "__main__":
    main()
