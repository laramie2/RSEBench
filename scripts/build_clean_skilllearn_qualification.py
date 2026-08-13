#!/usr/bin/env python3
"""Freeze clean-only qualification manifests for eight SkillLearn families."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SHARED_ROOT = (
    PROJECT_ROOT.parents[1] if ".worktrees" in PROJECT_ROOT.parts else PROJECT_ROOT
)
METHODS_ROOT = SHARED_ROOT / "methods/external"
OUTPUT_ROOT = PROJECT_ROOT / "benchmark/validation/clean_qualification_v1"
METHOD_SEEDS = (20260813, 20260814, 20260815)
FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
    "github-repo-analytics",
    "financial-analysis",
    "stock-data-visualization",
    "enterprise-information-search",
)


from rsebench.core1.dataset import (  # noqa: E402
    make_clean_split_paths_portable,
)
from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
)
from rsebench.hashing import sha256_file  # noqa: E402
from scripts.build_core1_splits import _skilllearn_task  # noqa: E402


def _family_split(family: str) -> CleanEvolutionSplitManifest:
    family_root = METHODS_ROOT / "skilllearnbench/tasks" / family
    instances = sorted(
        (path for path in family_root.iterdir() if path.is_dir()),
        key=lambda path: int(path.name.rsplit("-", 1)[1]),
    )
    if len(instances) not in {5, 6}:
        raise ValueError(f"SkillLearn family {family} requires five or six instances")
    tasks = [_skilllearn_task(instance) for instance in instances]
    metadata: dict[str, Any] = {
        "qualification_version": "clean-qualification-v1",
        "baseline": "skilllearn_self_feedback",
        "task_family": family,
        "feedback_mode": "self",
        "runtime": {
            "max_tool_turns": 16,
            "max_completion_tokens": 4096,
            "evolution_rounds": 2,
            "require_prebuilt_images": True,
        },
    }
    payload = {
        "benchmark": "skilllearnbench",
        "domain": "skill_learning",
        "seed": 20260813,
        "train": [task.model_dump(mode="json") for task in tasks[:2]],
        "validation": [tasks[2].model_dump(mode="json")],
        "clean_test": [task.model_dump(mode="json") for task in tasks[3:]],
        "metadata": metadata,
    }
    return CleanEvolutionSplitManifest(
        benchmark="skilllearnbench",
        domain="skill_learning",
        seed=20260813,
        source_hash=canonical_hash(payload),
        train=tasks[:2],
        validation=[tasks[2]],
        clean_test=tasks[3:],
        metadata=metadata,
    )


def _serialize(payload: Any) -> bytes:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_immutable(path: Path, payload: Any) -> Path:
    encoded = _serialize(payload)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"different SkillLearn manifest already exists: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return path


def build_clean_skilllearn_qualification(
    *,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Path]:
    portable_splits: dict[str, CleanEvolutionSplitManifest] = {}
    outputs: dict[str, Path] = {}
    family_root = output_root / "skilllearnbench"
    for family in FAMILIES:
        portable = make_clean_split_paths_portable(
            _family_split(family),
            project_root=PROJECT_ROOT,
            data_root=SHARED_ROOT / "data",
            methods_root=METHODS_ROOT,
        )
        portable_splits[family] = portable
        outputs[family] = _write_immutable(family_root / f"{family}.json", portable)

    seed_skill = PROJECT_ROOT / "benchmark/core1/seeds/skilllearn.md"
    index = {
        "schema_version": "rsebench.clean-skilllearn-manifest.v1",
        "qualification_version": "clean-qualification-v1",
        "families": list(FAMILIES),
        "method_seeds": list(METHOD_SEEDS),
        "seed_skill_hash": sha256_file(seed_skill),
        "outputs": {
            family: {
                "path": outputs[family].relative_to(output_root).as_posix(),
                "sizes": {
                    "train": len(portable_splits[family].train),
                    "validation": len(portable_splits[family].validation),
                    "clean_test": len(portable_splits[family].clean_test),
                },
                "source_hash": portable_splits[family].source_hash,
                "instance_ids": [
                    task.task_id
                    for task in (
                        portable_splits[family].train
                        + portable_splits[family].validation
                        + portable_splits[family].clean_test
                    )
                ],
            }
            for family in FAMILIES
        },
    }
    _write_immutable(output_root / "skilllearn_manifest.json", index)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_clean_skilllearn_qualification(output_root=args.output_root)
    print(json.dumps({family: str(path) for family, path in outputs.items()}, indent=2))


if __name__ == "__main__":
    main()
