"""Registry loading and cross-file validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def load_registry(path: Path | str) -> dict[str, Any]:
    """Load a YAML registry and require a mapping at the root."""
    registry_path = Path(path)
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"registry root must be a mapping: {registry_path}")
    return data


def validate_registries(root: Path | str) -> None:
    """Validate method pins, benchmark references, and split arithmetic."""
    registry_root = Path(root)
    methods = load_registry(registry_root / "methods.yaml").get("methods", {})
    benchmarks = load_registry(registry_root / "benchmarks.yaml").get(
        "benchmarks", {}
    )
    splits = load_registry(registry_root / "splits.yaml").get("splits", {})
    operators = load_registry(registry_root / "noise_operators.yaml").get(
        "operators", {}
    )

    if not methods or not benchmarks or not splits or not operators:
        raise ValueError("all registries must be non-empty")

    for name, row in methods.items():
        if not str(row.get("repository", "")).startswith("https://github.com/"):
            raise ValueError(f"method {name} has invalid repository")
        if not _COMMIT_RE.fullmatch(str(row.get("commit", ""))):
            raise ValueError(f"method {name} has invalid commit")

    valid_domains = {row["domain"] for row in benchmarks.values()}
    for name, row in splits.items():
        benchmark = row.get("benchmark")
        if benchmark not in benchmarks:
            raise ValueError(f"split {name} references unknown benchmark {benchmark}")
        if row.get("selection_mode") == "ordered_family_qualification":
            candidate_families = int(row.get("candidate_families", 0))
            target_families = int(row.get("target_qualified_families", 0))
            replicates = int(row.get("replicates", 0))
            if candidate_families < target_families or target_families < 1:
                raise ValueError(
                    f"split {name} has invalid family qualification counts"
                )
            if replicates != 3:
                raise ValueError(f"split {name} requires exactly three replicates")
            continue
        if row.get("selection_mode") == "frozen_ordered_groups":
            family_count = int(row.get("family_count", 0))
            tasks_per_family = int(row.get("tasks_per_family", 0))
            if family_count < 1 or tasks_per_family < 1:
                raise ValueError(f"split {name} has invalid frozen group counts")
            if int(row.get("total", 0)) != family_count * tasks_per_family:
                raise ValueError(f"split {name} frozen group total differs")
            if not row.get("release_id"):
                raise ValueError(f"split {name} frozen release identity is missing")
            continue
        total = int(row["total"])
        partition_total = (
            int(row["evolution"]) + int(row["validation"]) + int(row["test"])
        )
        if partition_total != total:
            raise ValueError(
                f"split {name} partitions total {partition_total}, expected {total}"
            )
        if int(row["pilot_evolve"]) + int(row["pilot_eval"]) > int(
            row["evolution"]
        ):
            raise ValueError(f"split {name} pilot exceeds evolution partition")

    for name, row in operators.items():
        if row.get("channel") not in {"C1", "C2", "C3", "C4"}:
            raise ValueError(f"operator {name} has invalid channel")
        if row.get("mechanism") not in {"M1", "M2", "M3", "M4", "M5", "M6"}:
            raise ValueError(f"operator {name} has invalid mechanism")
        unknown_domains = set(row.get("domains", [])) - valid_domains
        if unknown_domains:
            raise ValueError(
                f"operator {name} references unknown domains {sorted(unknown_domains)}"
            )
