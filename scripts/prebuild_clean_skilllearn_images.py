#!/usr/bin/env python3
"""Prebuild and audit Docker images for clean SkillLearn qualification."""

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

from rsebench.core1.dataset import resolve_clean_split_paths  # noqa: E402
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
)
from rsebench.evolution.skilllearn_executor import (  # noqa: E402
    DockerSkillLearnBackend,
)
from scripts.baselines.common_env import (  # noqa: E402,F401
    combined_method_env,
    methods_root,
)
from scripts.build_clean_skilllearn_qualification import FAMILIES  # noqa: E402


DEFAULT_MANIFEST_ROOT = (
    PROJECT_ROOT / "benchmark/validation/clean_qualification_v1/skilllearnbench"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs/preflight/clean-qualification-v1/skilllearn/image_manifest.json"
)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _ordered_manifests(root: Path) -> list[Path]:
    by_name = {path.stem: path for path in root.glob("*.json")}
    ordered = [by_name.pop(family) for family in FAMILIES if family in by_name]
    ordered.extend(by_name[name] for name in sorted(by_name))
    return ordered


def prebuild_images(
    *,
    manifest_root: Path,
    output: Path,
    require_existing: bool = False,
) -> dict[str, Any]:
    external_methods = methods_root()
    backend = DockerSkillLearnBackend(
        client=object(),
        require_prebuilt=require_existing,
    )
    payload: dict[str, Any] = {
        "schema_version": "rsebench.skilllearn-image-manifest.v1",
        "qualification_version": "clean-qualification-v1",
        "require_existing": require_existing,
        "images": [],
        "task_to_context_hash": {},
        "failures": [],
        "all_ready": False,
    }
    images: dict[str, dict[str, Any]] = {}
    for manifest_path in _ordered_manifests(manifest_root):
        portable = CleanEvolutionSplitManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        split = resolve_clean_split_paths(
            portable,
            project_root=PROJECT_ROOT,
            data_root=SHARED_ROOT / "data",
            methods_root=external_methods,
        )
        tasks = split.train + split.validation + split.clean_test
        for task in tasks:
            try:
                record = backend.prepare(
                    task,
                    output.parent / "records" / task.task_id,
                )
            except Exception as exc:
                payload["failures"].append(
                    {
                        "task_id": task.task_id,
                        "status": "failed",
                        "stderr": str(exc),
                    }
                )
                _write(output, payload)
                raise
            payload["task_to_context_hash"][task.task_id] = record.context_hash
            candidate = record.model_dump(mode="json")
            candidate["task_ids"] = [task.task_id]
            existing = images.get(record.context_hash)
            if existing is None:
                images[record.context_hash] = candidate
            else:
                if (
                    existing["image_tag"] != record.image_tag
                    or existing["image_id"] != record.image_id
                ):
                    raise RuntimeError(
                        f"conflicting image identity for context {record.context_hash}"
                    )
                existing["task_ids"].append(task.task_id)
    payload["images"] = [images[key] for key in sorted(images)]
    payload["all_ready"] = not payload["failures"]
    _write(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-root", type=Path, default=DEFAULT_MANIFEST_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-existing", action="store_true")
    args = parser.parse_args()
    prebuild_images(
        manifest_root=args.manifest_root,
        output=args.output,
        require_existing=args.require_existing,
    )
    print(args.output)


if __name__ == "__main__":
    main()
