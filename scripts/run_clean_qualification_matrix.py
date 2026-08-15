#!/usr/bin/env python3
"""Expand and execute a frozen clean qualification matrix in isolation."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.experiments.preflight import preflight_matrix  # noqa: E402
from rsebench.experiments.scheduler import (  # noqa: E402
    CommandRunner,
    ExperimentScheduler,
    ScheduledUnit,
)
from rsebench.hashing import sha256_file  # noqa: E402
from rsebench.selection import SelectionAction, SelectionStatus  # noqa: E402


DEFAULT_CONFIG = PROJECT_ROOT / "configs/validation/clean_qualification_v1.yaml"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs/runs/clean-qualification-20260813"
CLEAN_MATRIX_RUNNABLE_ACTIONS: dict[SelectionAction, int] = {
    "rerun_candidate_1": 1,
    "run_candidate_2": 2,
    "run_candidate_3": 3,
}


@dataclass(frozen=True)
class MatrixUnit:
    key: str
    benchmark: str
    family: str | None
    method_seed: int
    command: tuple[str, ...]
    experiment_id: str
    mutable_resource_keys: list[str]
    adapter_key: str
    adapter_max_parallel: int

    def scheduled(self, output_root: Path) -> ScheduledUnit:
        return ScheduledUnit(
            key=self.key,
            experiment_id=self.experiment_id,
            command=list(self.command),
            output_dir=str(output_root),
            mutable_resource_keys=self.mutable_resource_keys,
            adapter_key=self.adapter_key,
            adapter_max_parallel=self.adapter_max_parallel,
        )


def load_config(path: Path) -> dict[str, Any]:
    """Load a matrix config and retain its source path for relative resolution."""

    source = path.resolve()
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("clean qualification matrix config must be a mapping")
    payload["_config_path"] = str(source)
    return payload


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _command(
    launcher: str,
    manifest: str,
    method_seed: int,
    output_root: Path,
    *,
    seed_skill: str | None = None,
    image_manifest: str | None = None,
    family: str | None = None,
) -> tuple[str, ...]:
    values = [
        sys.executable,
        str(_project_path(launcher)),
        "--manifest",
        str(_project_path(manifest)),
        "--method-seed",
        str(method_seed),
        "--output-root",
        str(output_root),
    ]
    if seed_skill is not None:
        values.extend(("--seed-skill", str(_project_path(seed_skill))))
    if image_manifest is not None:
        values.extend(("--image-manifest", str(_project_path(image_manifest))))
    if family is not None:
        values.extend(("--family", family))
    return tuple(values)


def _unit_experiment_id(
    config: dict[str, Any],
    *,
    benchmark: str,
    family: str | None,
    method_seed: int,
    launcher: str,
    manifest: str,
    seed_skill: str | None,
    image_manifest: str | None,
) -> str:
    """Build the stable legacy scheduling identity used before formal preflight."""

    return canonical_hash(
        {
            "qualification_version": config["qualification_version"],
            "benchmark": benchmark,
            "family": family,
            "method_seed": method_seed,
            "launcher": launcher,
            "manifest": manifest,
            "seed_skill": seed_skill,
            "image_manifest": image_manifest,
        }
    )


def _resource_keys(
    values: Sequence[str],
    *,
    benchmark: str,
    family: str | None,
    method_seed: int,
) -> list[str]:
    return [
        value.format(
            benchmark=benchmark,
            family=family or "",
            method_seed=method_seed,
        )
        for value in values
    ]


def _expand_formal_units(
    config: dict[str, Any],
    *,
    root: Path,
) -> list[MatrixUnit]:
    units: list[MatrixUnit] = []
    matrix_seeds = [int(value) for value in config["method_seeds"]]
    for cell in config["cells"]:
        benchmark = str(cell["benchmark"])
        family = str(cell["family"]) if cell.get("family") is not None else None
        manifest = str(cell["manifest"])
        seed_skill = str(cell["seed_skill"])
        image_manifest = cell.get("image_manifest")
        seeds = [int(value) for value in cell.get("method_seeds") or matrix_seeds]
        for method_seed in seeds:
            units.append(
                MatrixUnit(
                    key=f"{cell['key']}:{method_seed}",
                    benchmark=benchmark,
                    family=family,
                    method_seed=method_seed,
                    command=_command(
                        str(cell["launcher"]),
                        manifest,
                        method_seed,
                        root,
                        seed_skill=(
                            seed_skill if cell.get("seed_skill_argument", True) else None
                        ),
                        image_manifest=(
                            str(image_manifest) if image_manifest is not None else None
                        ),
                        family=family,
                    ),
                    experiment_id=_unit_experiment_id(
                        config,
                        benchmark=benchmark,
                        family=family,
                        method_seed=method_seed,
                        launcher=str(cell["launcher"]),
                        manifest=manifest,
                        seed_skill=seed_skill,
                        image_manifest=(
                            str(image_manifest) if image_manifest is not None else None
                        ),
                    ),
                    mutable_resource_keys=_resource_keys(
                        cell.get("mutable_resource_keys", []),
                        benchmark=benchmark,
                        family=family,
                        method_seed=method_seed,
                    ),
                    adapter_key=str(cell["adapter_key"]),
                    adapter_max_parallel=int(cell.get("adapter_max_parallel", 1)),
                )
            )
    return units


def expand_units(
    config: dict[str, Any],
    *,
    output_root: Path | None = None,
) -> list[MatrixUnit]:
    """Expand either a formal cell matrix or the legacy clean config shape."""

    seeds = [int(value) for value in config["method_seeds"]]
    root = (
        output_root.resolve()
        if output_root is not None
        else _project_path(config["output_root"]).resolve()
    )
    if "cells" in config:
        return _expand_formal_units(config, root=root)

    units: list[MatrixUnit] = []
    for benchmark_config in config["benchmarks"]:
        benchmark = str(benchmark_config["benchmark"])
        unit_root = root if benchmark != "webshop" else root / benchmark
        adapter_key = str(
            benchmark_config.get(
                "adapter", "skilladaptor" if benchmark == "webshop" else "skillopt"
            )
        )
        adapter_max_parallel = int(
            benchmark_config.get(
                "adapter_max_parallel", 1 if adapter_key == "skilladaptor" else 2
            )
        )
        seed_skill = benchmark_config.get("seed_skill")
        for method_seed in seeds:
            units.append(
                MatrixUnit(
                    key=f"{benchmark}:{method_seed}",
                    benchmark=benchmark,
                    family=None,
                    method_seed=method_seed,
                    command=_command(
                        benchmark_config["launcher"],
                        benchmark_config["manifest"],
                        method_seed,
                        unit_root,
                        seed_skill=seed_skill if benchmark == "webshop" else None,
                    ),
                    experiment_id=_unit_experiment_id(
                        config,
                        benchmark=benchmark,
                        family=None,
                        method_seed=method_seed,
                        launcher=benchmark_config["launcher"],
                        manifest=benchmark_config["manifest"],
                        seed_skill=seed_skill,
                        image_manifest=None,
                    ),
                    mutable_resource_keys=list(
                        benchmark_config.get("mutable_resource_keys", [])
                    ),
                    adapter_key=adapter_key,
                    adapter_max_parallel=adapter_max_parallel,
                )
            )

    skilllearn = config.get("skilllearn")
    if skilllearn is None:
        return units
    declared_manifests = skilllearn.get("manifests", {})
    for family in skilllearn["families"]:
        manifest = str(
            declared_manifests.get(
                family,
                f"benchmark/validation/clean_qualification_v1/skilllearnbench/{family}.json",
            )
        )
        for method_seed in seeds:
            units.append(
                MatrixUnit(
                    key=f"skilllearnbench:{family}:{method_seed}",
                    benchmark="skilllearnbench",
                    family=str(family),
                    method_seed=method_seed,
                    command=_command(
                        skilllearn["launcher"],
                        manifest,
                        method_seed,
                        root / "skilllearnbench",
                        seed_skill=skilllearn["seed_skill"],
                        image_manifest=config["image_manifest"],
                        family=str(family),
                    ),
                    experiment_id=_unit_experiment_id(
                        config,
                        benchmark="skilllearnbench",
                        family=str(family),
                        method_seed=method_seed,
                        launcher=skilllearn["launcher"],
                        manifest=manifest,
                        seed_skill=skilllearn["seed_skill"],
                        image_manifest=config["image_manifest"],
                    ),
                    mutable_resource_keys=list(
                        skilllearn.get(
                            "mutable_resource_keys",
                            [f"docker:skilllearn:{family}"],
                        )
                    ),
                    adapter_key=str(skilllearn.get("adapter", "skilllearn")),
                    adapter_max_parallel=int(
                        skilllearn.get("adapter_max_parallel", 2)
                    ),
                )
            )
    return units


def select_units_from_status(
    units: Sequence[MatrixUnit],
    *,
    status_path: Path,
    required_action: SelectionAction,
    matrix_candidate_index: int,
) -> list[MatrixUnit]:
    """Select only matrix domains requesting the typed sequential action."""

    status = SelectionStatus.model_validate_json(status_path.read_text(encoding="utf-8"))
    if status.schema_version != "rsebench.selection-status.v1":
        raise ValueError(f"unsupported selection status schema: {status.schema_version}")
    try:
        action_candidate_index = CLEAN_MATRIX_RUNNABLE_ACTIONS[required_action]
    except KeyError as exc:
        raise ValueError(
            f"required action is not runnable by clean matrix: {required_action}"
        ) from exc
    if action_candidate_index != matrix_candidate_index:
        raise ValueError("selection action differs from matrix candidate index")
    requested = {
        benchmark
        for benchmark, row in status.domains.items()
        if row.next_action == required_action
    }
    matrix_domains = {unit.benchmark for unit in units}
    unknown = requested - matrix_domains
    if unknown:
        raise ValueError(f"selection status contains unknown matrix domains: {unknown}")
    selected = [unit for unit in units if unit.benchmark in requested]
    if not selected:
        raise ValueError(f"no units request action {required_action}")
    return selected


def _ensure_clean_worktree() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise RuntimeError("formal clean matrix requires a clean git worktree")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return head.stdout.strip()


def run_matrix(
    config_path: Path = DEFAULT_CONFIG,
    *,
    execute: bool = False,
    output_root: Path | None = None,
    stop_on_failure: bool = False,
    max_new_units: int | None = None,
    max_parallel: int = 4,
    command_runner: CommandRunner | None = None,
    selection_status: Path | None = None,
    required_action: SelectionAction | None = None,
) -> list[MatrixUnit]:
    """Dry-expand by default, or execute isolated units with resume state."""

    if max_new_units is not None and max_new_units < 1:
        raise ValueError("max_new_units must be positive")
    if stop_on_failure:
        raise ValueError("stop_on_failure conflicts with failure-isolated scheduling")
    config_path = config_path.resolve()
    config = load_config(config_path)
    if (
        execute
        and config.get("qualification_version") == "noise-screen-v1"
        and (selection_status is None or required_action is None)
    ):
        raise ValueError(
            "noise-screen execution requires selection_status and required_action"
        )
    if (selection_status is None) != (required_action is None):
        raise ValueError("selection_status and required_action must be provided together")
    root = (
        output_root.resolve()
        if output_root is not None
        else _project_path(config["output_root"]).resolve()
    )
    all_units = expand_units(config, output_root=root)
    units = all_units
    if selection_status is not None and required_action is not None:
        candidate_index = config.get("candidate_index")
        if candidate_index is None:
            raise ValueError("selection filtering requires matrix candidate_index")
        units = select_units_from_status(
            units,
            status_path=selection_status,
            required_action=required_action,
            matrix_candidate_index=int(candidate_index),
        )
    if not execute:
        return units

    git_head = _ensure_clean_worktree()
    config_hash = sha256_file(config_path)
    scheduled_units = [unit.scheduled(root) for unit in units]
    if "cells" in config:
        report = preflight_matrix(config_path, require_clean_worktree=False)
        scheduled_by_key = {unit.key: unit.scheduled for unit in report.units}
        missing = {unit.key for unit in units} - set(scheduled_by_key)
        if missing:
            raise ValueError(f"preflight omitted scheduled matrix units: {missing}")
        scheduled_units = [scheduled_by_key[unit.key] for unit in units]
        git_head = report.repository_commit
    candidate_index = config.get("candidate_index")
    scheduler_root = (
        root / f"candidate-{candidate_index}"
        if candidate_index is not None
        else root
    )
    scheduler = ExperimentScheduler(
        run_root=scheduler_root,
        project_root=PROJECT_ROOT,
        max_parallel=max_parallel,
        command_runner=command_runner,
        status_metadata={
            "qualification_version": config["qualification_version"],
            "config_path": str(config_path),
            "config_hash": config_hash,
            "git_head": git_head,
            "expected_units": len(all_units),
        },
    )
    scheduler.run(
        scheduled_units,
        max_new_units=max_new_units,
    )
    return units


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--max-new-units", type=int)
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--selection-status", type=Path)
    parser.add_argument(
        "--required-action",
        choices=tuple(CLEAN_MATRIX_RUNNABLE_ACTIONS),
    )
    args = parser.parse_args()
    units = run_matrix(
        args.config,
        execute=args.execute,
        output_root=args.output_root,
        stop_on_failure=args.stop_on_failure,
        max_new_units=args.max_new_units,
        max_parallel=args.max_parallel,
        selection_status=args.selection_status,
        required_action=args.required_action,
    )
    if not args.execute:
        for unit in units:
            print(" ".join(unit.command))
        print(f"units={len(units)} provider_calls=0")


if __name__ == "__main__":
    main()
