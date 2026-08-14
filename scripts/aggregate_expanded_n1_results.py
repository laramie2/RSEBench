#!/usr/bin/env python3
"""Aggregate expanded-N1 run outcomes and globally deduplicated token usage."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.usage import aggregate_token_usage_tree  # noqa: E402


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _domain(relative: Path) -> str:
    parts = relative.parts
    lane = parts[1] if len(parts) > 1 else "unknown"
    if lane.startswith("spreadsheet"):
        return "spreadsheet"
    if lane.startswith("officeqa"):
        return "document"
    if lane.startswith("webshop"):
        return "interactive"
    if lane == "skilllearn":
        return "skill_learning"
    return lane


def _load_overrides(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs", payload)
    if not isinstance(runs, dict):
        raise ValueError("status overrides must contain a run-id mapping")
    return runs


def _classify_run(run_dir: Path, override: dict[str, Any] | None) -> dict[str, Any]:
    result = _read_json(run_dir / "result.json")
    clean_gate = _read_json(run_dir / "clean" / "preflight.json")
    seed_gate = _read_json(run_dir / "seed" / "calibration.json")
    if override:
        status = str(override["status"])
    elif result and "metrics" in result:
        status = "completed"
    elif clean_gate and not clean_gate.get("passed", True):
        status = "clean_gate_failed"
    elif seed_gate and not seed_gate.get("passed", True):
        status = "seed_gate_failed"
    else:
        status = "incomplete"
    record: dict[str, Any] = {
        "run_id": run_dir.name,
        "status": status,
    }
    if result and "method" in result:
        record["method"] = result["method"]
    if result and "metrics" in result:
        record["metrics"] = result["metrics"]
    if seed_gate:
        record["seed_calibration"] = seed_gate
    if clean_gate:
        record["clean_preflight"] = clean_gate
    if override:
        record.update({key: value for key, value in override.items() if key != "status"})
    return record


def build_aggregate(
    run_root: Path, *, status_overrides: Path | None = None
) -> dict[str, Any]:
    overrides = _load_overrides(status_overrides)
    records: list[dict[str, Any]] = []
    for split_manifest in sorted((run_root / "paired").rglob("split_manifest.json")):
        run_dir = split_manifest.parent
        relative = run_dir.relative_to(run_root)
        record = _classify_run(run_dir, overrides.get(run_dir.name))
        record["domain"] = _domain(relative)
        record["path"] = relative.as_posix()
        records.append(record)

    domain_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        domain_records[record["domain"]].append(record)
    domains: dict[str, Any] = {}
    for domain, items in sorted(domain_records.items()):
        completed = [item for item in items if item["status"] == "completed"]
        positive = [
            item
            for item in completed
            if float(item["metrics"].get("evolution_gap", 0.0)) > 0.0
        ]
        conclusive = [
            item
            for item in completed
            if float(item["metrics"].get("gap_ci_low", 0.0)) > 0.0
        ]
        domains[domain] = {
            "run_count": len(items),
            "statuses": dict(sorted(Counter(item["status"] for item in items).items())),
            "completed_runs": len(completed),
            "positive_completed_runs": len(positive),
            "ci_excludes_zero_runs": len(conclusive),
        }

    return {
        "schema_version": "rsebench.expanded-n1-aggregate.v1",
        "run_root": str(run_root),
        "run_summary": dict(sorted(Counter(item["status"] for item in records).items())),
        "domains": domains,
        "runs": records,
        "token_usage": aggregate_token_usage_tree(run_root),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status-overrides", type=Path)
    args = parser.parse_args()
    payload = build_aggregate(args.run_root, status_overrides=args.status_overrides)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
