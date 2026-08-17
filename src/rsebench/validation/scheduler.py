"""Translate immutable validation cells into isolated scheduler units."""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Sequence

from rsebench.experiments.scheduler import ScheduledUnit
from rsebench.validation.contracts import ValidationCell


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "cell"


def _method_source(project_root: Path, method: str) -> Path:
    canonical = project_root / "methods" / "validated" / method / "source"
    if canonical.is_dir():
        return canonical.resolve()
    legacy = project_root / "methods" / "external" / method
    if legacy.is_dir():
        warnings.warn(
            f"using legacy method source for validation unit: {method}",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy.resolve()
    return canonical.resolve()


def _project_patch(project_root: Path, uri: str) -> Path:
    prefix = "rsebench-project://"
    if not uri.startswith(prefix):
        raise ValueError(f"release patch must use a project URI: {uri}")
    path = (project_root / uri.removeprefix(prefix)).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"release patch escapes project root: {uri}") from exc
    return path


def build_validation_units(
    cells: Sequence[ValidationCell],
    run_root: Path | str,
    *,
    project_root: Path | str,
) -> tuple[ScheduledUnit, ...]:
    """Build one lock-free unit per cell and freeze its launcher payload."""

    root = Path(run_root).resolve()
    project = Path(project_root).resolve()
    plans = root / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    units: list[ScheduledUnit] = []
    for cell in cells:
        slug = _safe_segment(cell.cell_id)
        plan_path = plans / f"{slug}.json"
        encoded = json.dumps(
            cell.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ) + "\n"
        if plan_path.exists() and plan_path.read_text(encoding="utf-8") != encoded:
            raise RuntimeError(f"validation cell plan differs: {plan_path}")
        plan_path.write_text(encoded, encoding="utf-8")
        units.append(
            ScheduledUnit(
                key=cell.cell_id,
                experiment_id=cell.identity_hash,
                command=[
                    "python",
                    "-m",
                    "rsebench.validation.worker",
                    "--cell",
                    str(plan_path),
                ],
                output_dir=str(root / "cells" / slug),
                mutable_resource_keys=[],
                adapter_key=f"validation:{cell.method_release_id}",
                adapter_max_parallel=16,
                source_dir=str(_method_source(project, cell.method)),
                source_mode=cell.source_mode,
                source_revision=cell.upstream_revision,
                patch_paths=[
                    str(_project_patch(project, patch.uri))
                    for patch in cell.patch_series
                ],
            )
        )
    if len({unit.key for unit in units}) != len(units):
        raise ValueError("validation unit keys must be unique")
    return tuple(units)


__all__ = ["build_validation_units"]
