#!/usr/bin/env python
"""Calibrate OfficeQA seed evaluation on a disjoint 30-task pool."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evolution.calibration import (  # noqa: E402
    EvidenceEligibility,
    OfficeQACalibrationReport,
    OfficeQACalibrationRun,
    OfficeQARuntime,
    officeqa_evidence_eligibility,
    select_officeqa_calibration_ids,
    select_runtime,
)
from rsebench.evolution.skillopt_executor import (  # noqa: E402
    SkillOptBudget,
    SkillOptExecutor,
)
from rsebench.generation import _load_evolution_tasks  # noqa: E402
from scripts.baselines.common_env import combined_method_env, methods_root  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    return parser.parse_args()


def _read_result_rows(evaluation_dir: Path) -> list[dict]:
    path = evaluation_dir / "native_eval/results.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _report_from_rows(
    runtime: OfficeQARuntime,
    rows: list[dict],
    eligibility: dict[str, EvidenceEligibility],
    evaluation_dir: Path,
    *,
    error: str | None = None,
) -> OfficeQACalibrationReport:
    expected = len(eligibility)
    if not rows:
        return OfficeQACalibrationReport(
            runtime=runtime,
            n_tasks=expected,
            score=0.0,
            parseable_answer_rate=0.0,
            systemic_failure_rate=1.0,
            oracle_parsed_pages_rate=0.0,
            eligible_count=0,
            failure_category_counts={"provider_failure": expected},
            evaluation_dir=str(evaluation_dir),
            error=error or "evaluation produced no task rows",
        )
    categories = Counter(str(row.get("failure_category") or "unknown") for row in rows)
    systemic = {"provider_failure", "missing_oracle_page"}
    eligible_count = sum(
        eligibility[str(row.get("id"))].eligible
        and str(row.get("failure_category") or "") not in systemic
        for row in rows
        if str(row.get("id")) in eligibility
    )
    return OfficeQACalibrationReport(
        runtime=runtime,
        n_tasks=expected,
        score=mean(float(row.get("hard", 0)) for row in rows),
        parseable_answer_rate=mean(
            bool(str(row.get("predicted_answer") or "").strip()) for row in rows
        ),
        systemic_failure_rate=mean(
            str(row.get("failure_category") or "") in systemic for row in rows
        ),
        oracle_parsed_pages_rate=mean(
            bool(row.get("oracle_parsed_pages_included", False)) for row in rows
        ),
        eligible_count=eligible_count,
        failure_category_counts=dict(sorted(categories.items())),
        evaluation_dir=str(evaluation_dir),
        error=error,
    )


def _render_report(result: OfficeQACalibrationRun) -> str:
    lines = [
        "# OfficeQA Runtime Calibration",
        "",
        f"Status: `{result.status}`",
        f"Calibration tasks: {len(result.calibration_ids)}",
        f"Selected runtime: `{result.selected_runtime.name if result.selected_runtime else 'none'}`",
        "",
        "| Runtime | Score | Parseable | Systemic | Oracle pages | Eligible | Gate |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    selected_name = result.selected_runtime.name if result.selected_runtime else None
    for report in result.reports:
        lines.append(
            f"| {report.runtime.name} | {report.score:.4f} | "
            f"{report.parseable_answer_rate:.4f} | {report.systemic_failure_rate:.4f} | "
            f"{report.oracle_parsed_pages_rate:.4f} | {report.eligible_count} | "
            f"{'pass' if report.runtime.name == selected_name else 'fail'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    environment = combined_method_env("skillopt")
    data_root = Path(environment.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    dataset_path = data_root / config["dataset_path"]
    rows = pd.read_csv(dataset_path).to_dict(orient="records")
    seed = int(config["seed"])
    calibration_ids = select_officeqa_calibration_ids(
        rows, size=int(config["calibration_size"]), seed=seed
    )
    by_id = {str(row["uid"]): row for row in rows}
    eligibility = {
        task_id: officeqa_evidence_eligibility(by_id[task_id])
        for task_id in calibration_ids
    }
    tasks = _load_evolution_tasks(config, data_root, calibration_ids)
    tasks = [
        task.model_copy(
            update={
                "metadata": {
                    **task.metadata,
                    "external_evidence_required": not eligibility[task.task_id].eligible,
                    "evidence_eligibility_reason": eligibility[task.task_id].reason,
                }
            }
        )
        for task in tasks
    ]

    output_root = args.output_root or Path(
        environment.get("RSEBENCH_OUTPUT_ROOT", PROJECT_ROOT / "outputs")
    ) / "runs/officeqa-calibration"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = output_root / f"{stamp}-skillopt"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (run_dir / "calibration_task_manifest.json").write_text(
        json.dumps(
            {
                "ids": calibration_ids,
                "evidence_eligibility": {
                    key: value.model_dump(mode="json") for key, value in eligibility.items()
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    method_root = methods_root() / "skillopt"
    seed_skill = method_root / "skillopt/envs/officeqa/skills/initial.md"
    reports: list[OfficeQACalibrationReport] = []
    gates = dict(config["gates"])
    for raw_runtime in config["runtimes"]:
        runtime = OfficeQARuntime.model_validate(raw_runtime)
        evaluation_dir = run_dir / runtime.name
        evaluation_dir.mkdir()
        executor = SkillOptExecutor(
            method_root=method_root,
            data_root=data_root,
            environment=environment,
            budget=SkillOptBudget(
                workers=int(config.get("workers", 2)),
                max_turns=runtime.max_tool_turns,
                max_completion_tokens=runtime.max_completion_tokens,
            ),
        )
        error: str | None = None
        try:
            executor.evaluate(
                skill_path=seed_skill,
                clean_test=tasks,
                output_dir=evaluation_dir,
                stage=runtime.name,
            )
        except RuntimeError as exc:
            error = str(exc)
        report = _report_from_rows(
            runtime,
            _read_result_rows(evaluation_dir),
            eligibility,
            evaluation_dir,
            error=error,
        )
        reports.append(report)
        selected = select_runtime(reports, **gates)
        if selected is not None:
            break
        if report.failure_category_counts and set(report.failure_category_counts) == {
            "provider_failure"
        }:
            break

    selected = select_runtime(reports, **gates)
    result = OfficeQACalibrationRun(
        run_dir=str(run_dir),
        status="calibrated" if selected else "blocked",
        calibration_ids=calibration_ids,
        evidence_eligibility=eligibility,
        reports=reports,
        selected_runtime=selected.runtime if selected else None,
    )
    (run_dir / "result.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "report.md").write_text(_render_report(result), encoding="utf-8")
    print(run_dir)
    print(result.status)
    if result.selected_runtime:
        print(result.selected_runtime.name)


if __name__ == "__main__":
    main()
