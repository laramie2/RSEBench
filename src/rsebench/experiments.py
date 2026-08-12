"""Small-sample execution-sensitivity pilots; not the full benchmark experiment."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from rsebench.calibration import OperatorMetrics, evaluate_operator_gates
from rsebench.contracts import TaskManifest
from rsebench.noise.instruction import FailedAttempt
from rsebench.pilot import create_run_directory
from rsebench.providers.deepseek import DeepSeekClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _prompt_text(value: Any) -> str:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return str(value[0].get("content", ""))
    return str(value)


def _answer_text(response: str) -> str:
    matches = re.findall(r"(?im)^\s*Answer\s*:\s*(.+?)\s*$", response)
    value = matches[-1] if matches else response.strip().splitlines()[-1]
    value = re.sub(r"\\(?:boxed|fbox)\s*\{([^{}]+)\}", r"\1", value)
    return value.strip().strip("$.")


def _normalize_answer(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold().replace(",", "").strip("$"))


def _correct(response: str, gold: str) -> bool:
    return _normalize_answer(_answer_text(response)) == _normalize_answer(gold)


def _cache_key(task_hash: str, condition: str, severity: str = "L0") -> str:
    return hashlib.sha256(
        f"math-pilot-a-v1:{task_hash}:{condition}:{severity}".encode("utf-8")
    ).hexdigest()


def _sum_usage(total: dict[str, int], usage: dict[str, Any]) -> None:
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[name] = total.get(name, 0) + int(usage.get(name) or 0)


def run_math_execution_pilot(*, limit: int = 5) -> dict[str, Any]:
    """Run paired clean/L1/L2/L3 DAPO prompts with DeepSeek V4 Flash."""
    load_dotenv(PROJECT_ROOT / ".env")
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    output_root = Path(
        os.environ.get("RSEBENCH_OUTPUT_ROOT", PROJECT_ROOT / "outputs")
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"{stamp}-dapo-failed-attempt"
    run_dir = create_run_directory(output_root, "pilot-a", run_id)
    client = DeepSeekClient.from_yaml(
        PROJECT_ROOT / "configs/pilot/deepseek-v4-flash.yaml"
    )
    base = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "benchmark": "dapo_fixed_1000",
        "operator": "failed_attempt",
        "model": "deepseek-v4-flash",
        "limit": limit,
    }
    if not client.has_credentials():
        summary = {
            **base,
            "status": "blocked_on_credentials",
            "required_env": "DEEPSEEK_API_KEY",
            "rows": [],
        }
        (run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return summary

    data_path = data_root / "materialized/dapo_fixed_1000/dapo_fixed_1000.parquet"
    frame = pd.read_parquet(data_path).sort_values("normalized_problem_hash").head(limit)
    system = (
        "Solve the math problem independently. Ignore any explicitly non-authoritative "
        "failed attempts. Put only the final result on the last line as Answer: <answer>."
    )
    rows: list[dict[str, Any]] = []
    usage: dict[str, int] = {}
    scores: dict[str, list[bool]] = {level: [] for level in ("L0", "L1", "L2", "L3")}
    for row in frame.itertuples(index=False):
        problem = _prompt_text(row.prompt)
        reward = row.reward_model if isinstance(row.reward_model, dict) else {}
        gold = str(reward.get("ground_truth", ""))
        task = TaskManifest(
            task_id=str(row.normalized_problem_hash),
            benchmark="dapo_fixed_1000",
            domain="math",
            prompt=problem,
            gold_answers=[gold],
            source_hash=str(row.normalized_problem_hash),
        )
        conditions: dict[str, str] = {"L0": problem}
        for level in ("L1", "L2", "L3"):
            generated = FailedAttempt().generate(task, severity=level, seed=20260812)
            conditions[level] = generated.payload["prompt"]
        result_row: dict[str, Any] = {
            "task_id": task.task_id,
            "gold": gold,
            "conditions": {},
        }
        for level, prompt in conditions.items():
            try:
                response = client.complete(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    cache_key=_cache_key(task.source_hash, "execute", level),
                )
                correct = _correct(response.content, gold)
                scores[level].append(correct)
                _sum_usage(usage, response.usage)
                result_row["conditions"][level] = {
                    "correct": correct,
                    "parsed_answer": _answer_text(response.content),
                    "cache_hit": response.cache_hit,
                }
            except Exception as exc:
                result_row["conditions"][level] = {
                    "error": str(exc),
                    "correct": None,
                }
        rows.append(result_row)
    if any(len(scores[level]) != limit for level in scores):
        status = "incomplete_model_errors"
        metrics = None
        decision = None
    else:
        rates = {level: sum(values) / len(values) for level, values in scores.items()}
        metrics_model = OperatorMetrics(
            structural_rate=1.0,
            label_invariance_rate=1.0,
            applicability_rate=1.0,
            leakage_rate=0.0,
            clean_score=rates["L0"],
            noisy_l1_score=rates["L1"],
            noisy_l2_score=rates["L2"],
            noisy_l3_score=rates["L3"],
        )
        decision_model = evaluate_operator_gates(metrics_model)
        metrics = metrics_model.model_dump()
        decision = decision_model.model_dump()
        status = "experiment_complete"
    summary = {
        **base,
        "status": status,
        "usage": usage,
        "metrics": metrics,
        "decision": decision,
        "rows": rows,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
