#!/usr/bin/env python3
"""Plan or run the fixed-artifact replays used by clean selection."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAYERS = {
    "spreadsheetbench_verified": "scripts/replay_fixed_skillopt_artifacts.py",
    "officeqa_full": "scripts/replay_fixed_skillopt_artifacts.py",
    "webshop": "scripts/replay_fixed_skilladaptor_artifacts.py",
    "skilllearnbench": "scripts/replay_fixed_skilllearn_artifacts.py",
}


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return (
        candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
    ).resolve()


def build_commands(spec: Mapping[str, Any]) -> list[list[str]]:
    jobs = spec.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("replay spec requires a non-empty jobs list")
    commands: list[list[str]] = []
    for job in jobs:
        if not isinstance(job, Mapping):
            raise ValueError("replay job must be an object")
        benchmark = str(job.get("benchmark") or "")
        replayer = REPLAYERS.get(benchmark)
        if replayer is None:
            raise ValueError(f"unsupported replay benchmark: {benchmark}")
        artifacts = job.get("artifacts")
        if not isinstance(artifacts, Mapping) or not artifacts:
            raise ValueError(f"replay job lacks artifacts: {benchmark}")
        command = [
            sys.executable,
            str((PROJECT_ROOT / replayer).resolve()),
            "--manifest",
            str(_resolve(str(job["manifest"]))),
            "--reference",
            str(job.get("reference") or "seed"),
            "--repeats",
            str(int(job.get("repeats", 3))),
            "--output-dir",
            str(_resolve(str(job["output_dir"]))),
        ]
        if job.get("resume") is True:
            command.append("--resume")
        if benchmark == "skilllearnbench":
            family = str(job.get("family") or "")
            if not family:
                raise ValueError("SkillLearn replay job requires family")
            command.extend(["--family", family])
            image_manifest = job.get("image_manifest")
            if not image_manifest:
                raise ValueError("SkillLearn replay job requires image_manifest")
            command.extend(["--image-manifest", str(_resolve(str(image_manifest)))])
        for label, raw_path in artifacts.items():
            command.extend(["--artifact", f"{label}={_resolve(str(raw_path))}"])
        commands.append(command)
    return commands


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-provider-cost", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.spec.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("replay spec must be an object")
    commands = build_commands(payload)
    if args.execute and not args.confirm_provider_cost:
        raise ValueError(
            "provider-backed replay matrix requires --confirm-provider-cost"
        )
    plan = {
        "schema_version": "rsebench.noise-screen-replay-matrix.v1",
        "commands": commands,
        "provider_calls": 0 if not args.execute else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not args.execute:
        print(args.output)
        return
    for command in commands:
        subprocess.run([*command, "--confirm-provider-cost"], check=True)
    print(args.output)


if __name__ == "__main__":
    main()
