#!/usr/bin/env python3
"""Freeze provider-free SkillFlow clean candidate identities."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rsebench.skillflow.contracts import (  # noqa: E402
    SkillFlowCleanConfig,
    SkillFlowInputManifest,
)
from rsebench.skillflow.manifest import build_input_manifest  # noqa: E402


DEFAULT_CONFIG = PROJECT_ROOT / "configs/experiments/skillflow-clean-qualification-v1.yaml"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "benchmark/validation/skillflow_clean_qualification_v1/input_manifest.json"
)


def _resolve_project_path(value: str) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (PROJECT_ROOT / candidate).resolve()


def _write_immutable(path: Path, manifest: SkillFlowInputManifest) -> None:
    encoded = (
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if path.exists() and path.read_bytes() != encoded:
        raise FileExistsError(f"different SkillFlow input manifest exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def build_manifest(
    *,
    config_path: Path = DEFAULT_CONFIG,
    data_root: Path | None = None,
    output_path: Path = DEFAULT_OUTPUT,
) -> SkillFlowInputManifest:
    config = SkillFlowCleanConfig.model_validate(
        yaml.safe_load(config_path.read_text(encoding="utf-8"))
    )
    root = data_root.resolve() if data_root is not None else _resolve_project_path(config.data_root)
    manifest = build_input_manifest(data_root=root, config=config)
    _write_immutable(output_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = build_manifest(
        config_path=args.config,
        data_root=args.data_root,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "families": len(manifest.families),
                "tasks": sum(len(family.tasks) for family in manifest.families),
                "provider_calls": manifest.provider_calls,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
