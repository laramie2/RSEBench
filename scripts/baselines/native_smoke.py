"""Shared CLI and subprocess helpers for native OpenAI-compatible baselines."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from scripts.baselines.common_env import (
    combined_method_env,
    methods_root,
    write_smoke_result,
)


LEVELS = ("transport", "structured", "tool", "native_task", "evolution")


def run_method_python(method: str, code: str) -> dict[str, Any]:
    root = methods_root() / method
    python = root / ".venv/bin/python"
    if not python.is_file():
        raise RuntimeError(f"baseline environment is missing: {python}")
    completed = subprocess.run(
        [str(python), "-c", code],
        cwd=root,
        env=combined_method_env(method),
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if completed.returncode:
        raise RuntimeError((completed.stdout + completed.stderr).strip())
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("baseline smoke returned no JSON evidence")
    payload = json.loads(lines[-1])
    if payload.get("model") != "deepseek-v4-flash":
        raise RuntimeError(f"unexpected model: {payload.get('model')}")
    return payload


def run_launcher(
    method: str, online_handler: Callable[[str], dict[str, Any]]
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=LEVELS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline-fixture", action="store_true")
    args = parser.parse_args()
    try:
        evidence = (
            {"offline_fixture": True, "model": "deepseek-v4-flash"}
            if args.offline_fixture
            else online_handler(args.level)
        )
        write_smoke_result(
            args.output,
            method=method,
            level=args.level,
            status="passed",
            detail="",
            evidence=evidence,
        )
        return 0
    except Exception as exc:
        write_smoke_result(
            args.output,
            method=method,
            level=args.level,
            status="failed",
            detail=str(exc),
            evidence={},
        )
        return 1


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_text",
        "description": "Write a text file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
}


def unsupported_online_level(level: str) -> dict[str, Any]:
    raise RuntimeError(f"online smoke level is not implemented yet: {level}")
