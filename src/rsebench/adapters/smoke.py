"""Serial, stop-on-first-failure baseline smoke orchestration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from rsebench.adapters.contracts import (
    SMOKE_LEVELS,
    BaselineAdapterSpec,
    SmokeLevel,
    SmokeLevelRecord,
    SmokeRunRecord,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LevelRunner = Callable[
    [BaselineAdapterSpec, SmokeLevel, Path], SmokeLevelRecord
]


def _redact(text: str) -> str:
    secret = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    return text.replace(secret, "[REDACTED]") if secret else text


def execute_adapter_level(
    spec: BaselineAdapterSpec, level: SmokeLevel, run_dir: Path
) -> SmokeLevelRecord:
    launcher = PROJECT_ROOT / spec.launcher
    if not launcher.is_file():
        return SmokeLevelRecord(
            level=level,
            status="blocked",
            detail=f"launcher is not implemented: {spec.launcher}",
        )
    level_dir = run_dir / level.value
    level_dir.mkdir(parents=True, exist_ok=False)
    completed = subprocess.run(
        [
            sys.executable,
            str(launcher),
            "--level",
            level.value,
            "--output",
            str(level_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    result_path = level_dir / "result.json"
    launcher_result = (
        json.loads(result_path.read_text(encoding="utf-8"))
        if result_path.is_file()
        else {}
    )
    detail = launcher_result.get("detail") or (
        completed.stdout + completed.stderr
    ).strip()
    evidence = dict(launcher_result.get("evidence") or {})
    evidence["exit_code"] = completed.returncode
    return SmokeLevelRecord(
        level=level,
        status=(
            launcher_result.get("status")
            or ("passed" if completed.returncode == 0 else "failed")
        ),
        detail=_redact(detail)[-4000:],
        evidence=evidence,
    )


def run_smoke(
    spec: BaselineAdapterSpec,
    *,
    through: SmokeLevel,
    output_root: Path | str,
    level_runner: LevelRunner = execute_adapter_level,
) -> SmokeRunRecord:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = Path(output_root) / f"{stamp}-{spec.name}"
    run_dir.mkdir(parents=True, exist_ok=False)
    requested_index = SMOKE_LEVELS.index(through)
    records: list[SmokeLevelRecord] = []
    for level in SMOKE_LEVELS[: requested_index + 1]:
        record = level_runner(spec, level, run_dir)
        records.append(record)
        if record.status != "passed":
            break
    status = records[-1].status if records and records[-1].status != "passed" else "passed"
    summary = SmokeRunRecord(
        method=spec.name,
        model=spec.model,
        through=through,
        status=status,
        run_dir=str(run_dir),
        levels=records,
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
