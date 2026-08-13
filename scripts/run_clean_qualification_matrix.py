#!/usr/bin/env python3
"""Expand and execute the frozen clean qualification matrix sequentially."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.hashing import sha256_file, sha256_tree  # noqa: E402


DEFAULT_CONFIG = PROJECT_ROOT / "configs/validation/clean_qualification_v1.yaml"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs/runs/clean-qualification-20260813"


@dataclass(frozen=True)
class MatrixUnit:
    key: str
    benchmark: str
    family: str | None
    method_seed: int
    command: tuple[str, ...]


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
                        seed_skill=benchmark_config.get("seed_skill")
                        if benchmark == "webshop"
                        else None,
                    ),
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


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _run_dir(stdout: str) -> Path:
    for line in stdout.splitlines():
        candidate = Path(line.strip())
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.is_dir():
            return candidate.resolve()
    raise RuntimeError("launcher succeeded without reporting an existing run directory")


def _summarize(status: dict[str, Any]) -> None:
    rows = status["units"]
    status["terminal_units"] = len(rows)
    status["completed_units"] = sum(row["status"] == "completed" for row in rows)
    status["failed_units"] = sum(row["status"] == "failed" for row in rows)


def run_matrix(
    config_path: Path = DEFAULT_CONFIG,
    *,
    execute: bool = False,
    output_root: Path | None = None,
    stop_on_failure: bool = False,
    max_new_units: int | None = None,
) -> list[MatrixUnit]:
    """Dry-expand by default, or execute formal units sequentially with resume state."""

    if max_new_units is not None and max_new_units < 1:
        raise ValueError("max_new_units must be positive")
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
    status_path = root / "matrix_status.json"
    if status_path.is_file():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status.get("config_hash") != config_hash:
            raise RuntimeError("matrix config hash differs from existing resume state")
        if status.get("git_head") not in {None, git_head}:
            raise RuntimeError("git HEAD differs from existing resume state")
    else:
        status = {
            "schema_version": "rsebench.clean-qualification-matrix-status.v1",
            "qualification_version": config["qualification_version"],
            "config_path": str(config_path),
            "config_hash": config_hash,
            "git_head": git_head,
            "expected_units": len(units),
            "terminal_units": 0,
            "completed_units": 0,
            "failed_units": 0,
            "units": [],
        }
    terminal_keys = {row["key"] for row in status["units"]}
    new_terminal_units = 0
    for unit in units:
        if unit.key in terminal_keys:
            continue
        if max_new_units is not None and new_terminal_units >= max_new_units:
            break
        completed = subprocess.run(
            list(unit.command),
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        row: dict[str, Any] = {
            "key": unit.key,
            "benchmark": unit.benchmark,
            "family": unit.family,
            "method_seed": unit.method_seed,
            "command": list(unit.command),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode == 0:
            try:
                run_dir = _run_dir(completed.stdout)
                row.update(
                    status="completed",
                    run_dir=str(run_dir),
                    result_hash=sha256_tree(run_dir),
                )
            except Exception as exc:
                row.update(status="failed", error=str(exc))
        else:
            row.update(status="failed", error="launcher returned non-zero status")
        status["units"].append(row)
        terminal_keys.add(unit.key)
        new_terminal_units += 1
        _summarize(status)
        _write_status(status_path, status)
        if row["status"] == "failed" and stop_on_failure:
            break
    return units


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--max-new-units", type=int)
    args = parser.parse_args()
    units = run_matrix(
        args.config,
        execute=args.execute,
        output_root=args.output_root,
        stop_on_failure=args.stop_on_failure,
        max_new_units=args.max_new_units,
    )
    if not args.execute:
        for unit in units:
            print(" ".join(unit.command))
        print(f"units={len(units)} provider_calls=0")


if __name__ == "__main__":
    main()
