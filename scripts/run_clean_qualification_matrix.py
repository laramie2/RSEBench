#!/usr/bin/env python3
"""Expand and execute a frozen clean qualification matrix in isolation."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.experiments.scheduler import (  # noqa: E402
    CommandRunner,
    ExperimentScheduler,
    ScheduledUnit,
)
from rsebench.hashing import sha256_file  # noqa: E402


DEFAULT_CONFIG = PROJECT_ROOT / "configs/validation/clean_qualification_v1.yaml"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs/runs/clean-qualification-20260813"


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


def expand_units(
    config: dict[str, Any],
    *,
    output_root: Path | None = None,
) -> list[MatrixUnit]:
    """Expand three domain units plus eight SkillLearn families per seed."""

    seeds = [int(value) for value in config["method_seeds"]]
    root = (
        output_root.resolve()
        if output_root is not None
        else _project_path(config["output_root"]).resolve()
    )
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

    skilllearn = config["skilllearn"]
    for family in skilllearn["families"]:
        manifest = (
            f"benchmark/validation/clean_qualification_v1/skilllearnbench/{family}.json"
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
) -> list[MatrixUnit]:
    """Dry-expand by default, or execute isolated units with resume state."""

    if max_new_units is not None and max_new_units < 1:
        raise ValueError("max_new_units must be positive")
    if stop_on_failure:
        raise ValueError("stop_on_failure conflicts with failure-isolated scheduling")
    config_path = config_path.resolve()
    config = load_config(config_path)
    root = (
        output_root.resolve()
        if output_root is not None
        else _project_path(config["output_root"]).resolve()
    )
    units = expand_units(config, output_root=root)
    if not execute:
        return units

    git_head = _ensure_clean_worktree()
    config_hash = sha256_file(config_path)
    scheduler = ExperimentScheduler(
        run_root=root,
        project_root=PROJECT_ROOT,
        max_parallel=max_parallel,
        command_runner=command_runner,
        status_metadata={
            "qualification_version": config["qualification_version"],
            "config_path": str(config_path),
            "config_hash": config_hash,
            "git_head": git_head,
            "expected_units": len(units),
        },
    )
    scheduler.run(
        [unit.scheduled(root) for unit in units],
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
    args = parser.parse_args()
    units = run_matrix(
        args.config,
        execute=args.execute,
        output_root=args.output_root,
        stop_on_failure=args.stop_on_failure,
        max_new_units=args.max_new_units,
        max_parallel=args.max_parallel,
    )
    if not args.execute:
        for unit in units:
            print(" ".join(unit.command))
        print(f"units={len(units)} provider_calls=0")


if __name__ == "__main__":
    main()
