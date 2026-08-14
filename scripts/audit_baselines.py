#!/usr/bin/env python
"""Audit pinned baseline checkouts without modifying them."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from rsebench.registry import load_registry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _git(target: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(target), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def _tree_size(target: Path) -> int:
    result = subprocess.check_output(["du", "-sb", str(target)], text=True)
    return int(result.split()[0])


def audit() -> dict:
    load_dotenv(PROJECT_ROOT / ".env")
    methods_root = Path(
        os.environ.get(
            "RSEBENCH_METHODS_ROOT", PROJECT_ROOT / "methods" / "external"
        )
    )
    methods = load_registry(PROJECT_ROOT / "benchmark/registry/methods.yaml")[
        "methods"
    ]
    rows: dict[str, dict] = {}
    for name, spec in methods.items():
        target = methods_root / name
        row = {
            "path": str(target),
            "expected_commit": spec["commit"],
            "expected_origin": spec["repository"],
            "code_status": spec["code_status"],
            "present": (target / ".git").is_dir(),
        }
        if row["present"]:
            head = _git(target, "rev-parse", "HEAD")
            origin = _git(target, "remote", "get-url", "origin")
            row.update(
                {
                    "head": head,
                    "origin": origin,
                    "dirty": bool(_git(target, "status", "--porcelain")),
                    "bytes": _tree_size(target),
                    "verified": head == spec["commit"] and origin == spec["repository"],
                }
            )
        else:
            row["verified"] = False
        rows[name] = row
    return {"methods_root": str(methods_root), "methods": rows}


def main() -> None:
    report = audit()
    output_root = PROJECT_ROOT / "outputs" / "audits"
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "baselines.json"
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(output_path)
    for name, row in report["methods"].items():
        print(f"{name}\tpresent={row['present']}\tverified={row['verified']}")


if __name__ == "__main__":
    main()
