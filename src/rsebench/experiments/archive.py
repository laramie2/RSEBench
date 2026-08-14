"""Portable manifests for historical diagnostic experiment trees."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rsebench.hashing import sha256_tree


def build_diagnostic_manifest(
    run_root: Path,
    *,
    output_root: Path,
    git_head: str,
) -> dict[str, Any]:
    """Describe an existing non-formal run without embedding host paths."""

    resolved_run = Path(run_root).resolve()
    resolved_output = Path(output_root).resolve()
    relative = resolved_run.relative_to(resolved_output)
    return {
        "schema_version": "rsebench.diagnostic-release.v1",
        "track": "diagnostic",
        "qualification_version": "clean-qualification-v1",
        "git_head": git_head,
        "run_locator": f"rsebench-output://{relative.as_posix()}",
        "run_root_hash": sha256_tree(resolved_run),
        "formal_qualification": False,
    }
