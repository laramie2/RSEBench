#!/usr/bin/env python
"""Schedule, resume, and audit the 16 Core-1 validation cells."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import yaml
from pydantic import Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.contracts import StrictModel  # noqa: E402


DOMAIN_ORDER = ("spreadsheet", "document", "skill_learning", "interactive")
STAGE_ORDER = ("N3", "N4", "N2", "N1")
FINAL_STATUSES = {"passed", "null", "opposite", "blocked"}


class ScreenCell(StrictModel):
    cell_id: str
    benchmark: str
    domain: str
    method: str
    stage: Literal["N1", "N2", "N3", "N4"]
    operator: str
    form: Literal["static", "runtime"]
    evolution_size: int = Field(ge=1)
    validation_size: int = Field(ge=0)
    clean_test_size: int = Field(ge=1)
    token_cap: int = Field(ge=1)
    estimated_tokens: int = Field(default=0, ge=0)


def build_core1_cells(root: Path = PROJECT_ROOT) -> list[ScreenCell]:
    profiles: list[ScreenCell] = []
    for path in (root / "configs/core1").glob("*/*.yaml"):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        sizes = payload["sizes"]
        profiles.append(
            ScreenCell(
                cell_id=f"{payload['domain']}--{payload['benchmark']}--{payload['stage']}",
                benchmark=payload["benchmark"],
                domain=payload["domain"],
                method=payload["primary_method"],
                stage=payload["stage"],
                operator=payload["operator"],
                form=payload["form"],
                evolution_size=int(sizes["evolution"]),
                validation_size=int(sizes["validation"]),
                clean_test_size=int(sizes["clean_test"]),
                token_cap=int(payload["token_cap"]),
            )
        )
    profiles.sort(
        key=lambda cell: (
            DOMAIN_ORDER.index(cell.domain),
            STAGE_ORDER.index(cell.stage),
        )
    )
    return profiles


def classify_result(*, clean_score: float, noisy_score: float) -> str:
    gap = clean_score - noisy_score
    if gap > 1e-12:
        return "passed"
    if gap < -1e-12:
        return "opposite"
    return "null"


class Core1Screen:
    def __init__(
        self,
        *,
        output_dir: Path | str,
        dispatcher: Callable[[ScreenCell, bool], dict[str, Any]],
    ) -> None:
        self.output_dir = Path(output_dir)
        self.dispatcher = dispatcher

    def _write(self, name: str, payload: dict[str, Any]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)

    def run(
        self,
        cells: list[ScreenCell],
        *,
        smoke_only: bool,
        resume: bool,
    ) -> dict[str, Any]:
        previous: dict[str, dict[str, Any]] = {}
        previous_updated_at: str | None = None
        result_path = self.output_dir / "results.json"
        if resume and result_path.is_file():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            previous_updated_at = payload.get("updated_at")
            previous = {row["cell_id"]: row for row in payload.get("cells", [])}
        self._write(
            "screen_manifest.json",
            {
                "schema_version": "rsebench.core1-screen.v1",
                "model": "deepseek-v4-flash",
                "thinking": "disabled",
                "smoke_only": smoke_only,
                "cells": [cell.model_dump(mode="json") for cell in cells],
            },
        )
        rows: list[dict[str, Any]] = []
        dispatched_any = False
        for cell in cells:
            if cell.cell_id in previous and previous[cell.cell_id].get("status") in FINAL_STATUSES:
                rows.append(previous[cell.cell_id])
                continue
            base = {
                **cell.model_dump(mode="json"),
                "smoke_only": smoke_only,
                "clean_score": None,
                "noisy_score": None,
                "clean_minus_noisy": None,
                "run_dir": None,
                "token_usage": None,
                "detail": "",
            }
            if cell.estimated_tokens > cell.token_cap:
                row = {
                    **base,
                    "status": "blocked",
                    "detail": (
                        f"estimated token cost {cell.estimated_tokens} exceeds "
                        f"profile token cap {cell.token_cap}"
                    ),
                }
            else:
                dispatched_any = True
                try:
                    dispatched = self.dispatcher(cell, smoke_only)
                    clean = dispatched.get("clean_score")
                    noisy = dispatched.get("noisy_score")
                    if smoke_only and (clean is None or noisy is None):
                        status = "passed"
                    elif clean is None or noisy is None:
                        raise ValueError("efficacy dispatch returned no paired scores")
                    else:
                        status = classify_result(
                            clean_score=float(clean), noisy_score=float(noisy)
                        )
                    row = {
                        **base,
                        **dispatched,
                        "status": status,
                        "clean_minus_noisy": (
                            float(clean) - float(noisy)
                            if clean is not None and noisy is not None
                            else None
                        ),
                    }
                except Exception as exc:  # persist evidence; never fake scores
                    row = {
                        **base,
                        "status": "blocked",
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
            rows.append(row)
            snapshot = {
                "schema_version": "rsebench.core1-screen-results.v1",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "cells": rows,
            }
            self._write("results.json", snapshot)
        final = {
            "schema_version": "rsebench.core1-screen-results.v1",
            "updated_at": (
                previous_updated_at
                if previous_updated_at is not None and not dispatched_any
                else datetime.now(timezone.utc).isoformat()
            ),
            "cells": rows,
        }
        self._write("results.json", final)
        return final


class SubprocessDispatcher:
    def __init__(self, *, output_dir: Path, root: Path = PROJECT_ROOT) -> None:
        self.output_dir = output_dir
        self.root = root

    def _split(self, cell: ScreenCell) -> Path:
        path = self.root / f"benchmark/core1/splits/{cell.benchmark}/{cell.stage}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Core-1 split is not materialized: {path}")
        return path

    def _seed(self, cell: ScreenCell) -> Path:
        if cell.benchmark == "spreadsheetbench_verified":
            relative = "skillopt/envs/spreadsheetbench/skills/initial.md"
            return Path(self._methods_root()) / relative
        if cell.benchmark == "officeqa_full":
            relative = "skillopt/envs/officeqa/skills/initial.md"
            return Path(self._methods_root()) / relative
        suffix = "skilllearn.md" if cell.benchmark == "skilllearnbench" else "skilladaptor_webshop.json"
        return self.root / "benchmark/core1/seeds" / suffix

    @staticmethod
    def _methods_root() -> str:
        from scripts.baselines.common_env import methods_root

        return str(methods_root())

    def _command(self, cell: ScreenCell, smoke_only: bool) -> list[str]:
        train = 1 if smoke_only else cell.evolution_size
        validation = min(1, cell.validation_size) if smoke_only else cell.validation_size
        test = 2 if smoke_only else cell.clean_test_size
        split = self._split(cell)
        cell_output = self.output_dir / "runs" / cell.cell_id
        common_limits = [
            "--train-limit", str(train),
            "--validation-limit", str(validation),
            "--test-limit", str(test),
        ]
        if cell.method == "skillopt":
            return [
                sys.executable,
                str(self.root / "scripts/run_paired_skillopt.py"),
                "--manifest", str(split),
                "--stage", cell.stage,
                "--output-root", str(cell_output),
                *common_limits,
                "--max-steps", "1",
                "--max-turns", "3",
            ]
        if cell.method.startswith("skilllearn_"):
            command = [
                sys.executable,
                str(self.root / "scripts/run_paired_skilllearn.py"),
                "--split", str(split),
                "--seed-skill", str(self._seed(cell)),
                "--feedback-mode", "teacher" if "teacher" in cell.method else "self",
                "--output-root", str(cell_output),
                "--train-limit", str(train),
                "--test-limit", str(test),
            ]
            if cell.form == "runtime":
                command.extend(
                    [
                        "--evidence-spec",
                        str(self.root / f"benchmark/core1/runtime/{cell.benchmark}/{cell.stage}.json"),
                    ]
                )
            return command
        return [
            sys.executable,
            str(self.root / "scripts/run_paired_skilladaptor.py"),
            "--manifest", str(split),
            "--seed-skill", str(self._seed(cell)),
            "--stage", cell.stage,
            "--output-root", str(cell_output),
            *common_limits,
            "--max-episode-steps", "4" if smoke_only else "8",
        ]

    def __call__(self, cell: ScreenCell, smoke_only: bool) -> dict[str, Any]:
        command = self._command(cell, smoke_only)
        completed = subprocess.run(
            command,
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        cell_dir = self.output_dir / "cells" / cell.cell_id
        cell_dir.mkdir(parents=True, exist_ok=True)
        (cell_dir / "command.json").write_text(
            json.dumps(command, indent=2) + "\n", encoding="utf-8"
        )
        (cell_dir / "stdout.log").write_text(completed.stdout or "", encoding="utf-8")
        (cell_dir / "stderr.log").write_text(completed.stderr or "", encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "")[-2000:])
        run_dir = next(
            (
                Path(line.strip())
                for line in completed.stdout.splitlines()
                if line.strip() and Path(line.strip()).is_dir()
            ),
            None,
        )
        if run_dir is None or not (run_dir / "result.json").is_file():
            raise RuntimeError("paired runner did not report a result directory")
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        return {
            "clean_score": result["clean_evaluation"]["score"],
            "noisy_score": result["noisy_evaluation"]["score"],
            "run_dir": str(run_dir),
            "token_usage": result.get("token_usage"),
            "metrics": result.get("metrics"),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=DOMAIN_ORDER)
    parser.add_argument("--stage", choices=("N1", "N2", "N3", "N4"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/runs/core1-screen"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cells = [
        cell
        for cell in build_core1_cells()
        if (args.domain is None or cell.domain == args.domain)
        and (args.stage is None or cell.stage == args.stage)
    ]
    if args.audit_only:
        results = args.output_dir / "results.json"
        if not results.is_file():
            raise FileNotFoundError(f"screen results missing: {results}")
        payload = json.loads(results.read_text(encoding="utf-8"))
        unknown = [row for row in payload["cells"] if row.get("status") not in FINAL_STATUSES]
        if unknown:
            raise ValueError(f"screen has non-final cells: {len(unknown)}")
        print(json.dumps({"cells": len(payload["cells"]), "valid": True}))
        return
    dispatcher = SubprocessDispatcher(output_dir=args.output_dir)
    result = Core1Screen(output_dir=args.output_dir, dispatcher=dispatcher).run(
        cells, smoke_only=args.smoke_only, resume=args.resume
    )
    print(json.dumps({row["cell_id"]: row["status"] for row in result["cells"]}, sort_keys=True))


if __name__ == "__main__":
    main()
