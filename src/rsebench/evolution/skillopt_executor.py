"""Native SkillOpt executor for paired DeepSeek self-evolution experiments."""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from rsebench.contracts import TaskManifest
from rsebench.evolution.contracts import EvolutionArmManifest, EvolutionSplitManifest
from rsebench.evolution.runner import EvaluationResult, EvolutionArtifact
from rsebench.evolution.skillopt_bridge import (
    materialize_skillopt_clean_test,
    materialize_skillopt_split,
)
from rsebench.hashing import sha256_file


MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class SkillOptBudget:
    max_steps: int = 1
    batch_size: int = 4
    workers: int = 1
    max_turns: int = 3
    max_completion_tokens: int = 2048
    edit_budget: int = 2
    minibatch_size: int = 2


_CONFIGS = {
    "spreadsheetbench_verified": "configs/spreadsheetbench/default.yaml",
    "officeqa_full": "configs/officeqa/default.yaml",
    "livemathematicianbench": "configs/livemathematicianbench/default.yaml",
    "dapo_fixed_1000": "configs/dapo/default.yaml",
    "docvqa_10pct": "configs/docvqa/default.yaml",
    "searchqa_skillopt": "configs/searchqa/default.yaml",
}


class SkillOptExecutor:
    def __init__(
        self,
        *,
        method_root: Path | str,
        data_root: Path | str,
        budget: SkillOptBudget | None = None,
        command_runner: Callable[..., Any] = subprocess.run,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.method_root = Path(method_root).resolve()
        self.data_root = Path(data_root).resolve()
        self.budget = budget or SkillOptBudget()
        self.command_runner = command_runner
        if environment is None:
            from scripts.baselines.common_env import combined_method_env

            environment = combined_method_env("skillopt")
        self.environment = dict(environment)
        project_src = str(Path(__file__).resolve().parents[2])
        inherited_pythonpath = self.environment.get("PYTHONPATH", "").strip()
        pythonpath_parts = [project_src]
        if inherited_pythonpath:
            pythonpath_parts.append(inherited_pythonpath)
        self.environment["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        self.python = self.method_root / ".venv/bin/python"
        if not self.python.is_file():
            raise FileNotFoundError(f"SkillOpt Python missing: {self.python}")

    def _config(self, benchmark: str) -> Path:
        try:
            relative = _CONFIGS[benchmark]
        except KeyError as exc:
            raise ValueError(f"SkillOpt does not support benchmark: {benchmark}") from exc
        config = self.method_root / relative
        if not config.is_file():
            raise FileNotFoundError(f"SkillOpt config missing: {config}")
        return config

    def _domain_options(self, benchmark: str) -> list[str]:
        options = [
            f"env.max_turns={self.budget.max_turns}",
            f"env.max_completion_tokens={self.budget.max_completion_tokens}",
            f"env.workers={self.budget.workers}",
        ]
        if benchmark == "spreadsheetbench_verified":
            options.extend(("env.mode=single", "env.data_root="))
        elif benchmark == "officeqa_full":
            corpus = self.data_root / "materialized/officeqa_full/corpus"
            if not corpus.is_dir():
                raise FileNotFoundError(f"OfficeQA corpus missing: {corpus}")
            parsed_root = self.data_root / "materialized/officeqa_full/parsed"
            if not (parsed_root / "jsons").is_dir():
                raise FileNotFoundError(
                    f"OfficeQA parsed pages missing: {parsed_root}; "
                    "run scripts/materialize_officeqa_parsed_pages.py"
                )
            options.extend(
                (
                    f"env.data_dirs={corpus},{parsed_root}",
                    "env.search_mode=offline",
                    "env.use_local_tools=true",
                    f"env.max_tool_turns={self.budget.max_turns}",
                )
            )
        elif benchmark == "livemathematicianbench":
            options.extend(
                (
                    "env.shuffle_choices=false",
                    "env.use_theorem=false",
                    "env.use_sketch=false",
                )
            )
        elif benchmark == "dapo_fixed_1000":
            options.append("env.exec_timeout=180")
        elif benchmark == "docvqa_10pct":
            options.extend(("env.image_detail=high", "env.exec_timeout=180"))
        return options

    def _common_options(self, benchmark: str, split_dir: Path) -> list[str]:
        return [
            "model.backend=openai_compatible",
            "model.optimizer_backend=openai_compatible",
            "model.target_backend=openai_compatible",
            f"model.optimizer={MODEL}",
            f"model.target={MODEL}",
            "model.reasoning_effort=",
            "env.split_mode=split_dir",
            f"env.split_dir={split_dir}",
            *self._domain_options(benchmark),
        ]

    def _redact(self, text: str) -> str:
        redacted = text
        for name in (
            "DEEPSEEK_API_KEY",
            "TARGET_OPENAI_COMPATIBLE_API_KEY",
            "OPTIMIZER_OPENAI_COMPATIBLE_API_KEY",
        ):
            secret = self.environment.get(name, "").strip()
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted

    def _run(self, command: list[str], record_dir: Path) -> None:
        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / "command.json").write_text(
            json.dumps(command, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        completed = self.command_runner(
            command,
            cwd=self.method_root,
            env=self.environment,
            capture_output=True,
            text=True,
        )
        (record_dir / "stdout.log").write_text(
            self._redact(str(completed.stdout or "")), encoding="utf-8"
        )
        (record_dir / "stderr.log").write_text(
            self._redact(str(completed.stderr or "")), encoding="utf-8"
        )
        if completed.returncode != 0:
            tail = self._redact(str(completed.stderr or completed.stdout or ""))[-2000:]
            raise RuntimeError(
                f"SkillOpt command failed with exit {completed.returncode}: {tail}"
            )

    def evolve(
        self,
        *,
        arm: EvolutionArmManifest,
        split: EvolutionSplitManifest,
        seed_skill_path: Path,
        output_dir: Path,
    ) -> EvolutionArtifact:
        native_split = materialize_skillopt_split(
            split, arm=arm.arm, output_dir=output_dir / "native_split"
        )
        native_output = output_dir / "native_train"
        batch_size = min(self.budget.batch_size, max(1, len(split.train)))
        command = [
            str(self.python),
            str(self.method_root / "scripts/train.py"),
            "--config",
            str(self._config(split.benchmark)),
            "--skill_init",
            str(seed_skill_path.resolve()),
            "--num_epochs",
            "1",
            "--train_size",
            str(len(split.train)),
            "--batch_size",
            str(batch_size),
            "--accumulation",
            "1",
            "--seed",
            str(arm.method_seed),
            "--edit_budget",
            str(self.budget.edit_budget),
            "--min_edit_budget",
            "1",
            "--merge_batch_size",
            str(self.budget.minibatch_size),
            "--max_analyst_rounds",
            "1",
            "--sel_env_num",
            str(len(split.validation)),
            "--eval_test",
            "false",
            "--use_gate",
            "true",
            "--max_steps",
            str(self.budget.max_steps),
            "--max_api_workers",
            str(self.budget.workers),
            "--analyst_workers",
            str(self.budget.workers),
            "--minibatch_size",
            str(self.budget.minibatch_size),
            "--use_slow_update",
            "false",
            "--use_meta_skill",
            "false",
            "--split_dir",
            str(native_split),
            "--workers",
            str(self.budget.workers),
            "--out_root",
            str(native_output),
            "--cfg-options",
            *self._common_options(split.benchmark, native_split),
        ]
        self._run(command, output_dir / "command")
        artifact = native_output / "best_skill.md"
        if not artifact.is_file():
            raise RuntimeError(f"SkillOpt produced no best skill: {artifact}")
        diagnostics: dict[str, Any] = {}
        summary_path = native_output / "summary.json"
        if summary_path.is_file():
            diagnostics["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
        return EvolutionArtifact(
            skill_path=str(artifact.resolve()),
            skill_hash=sha256_file(artifact),
            diagnostics=diagnostics,
        )

    def evaluate(
        self,
        *,
        skill_path: Path,
        clean_test: list[TaskManifest],
        output_dir: Path,
        stage: str,
    ) -> EvaluationResult:
        benchmark = clean_test[0].benchmark
        native_split = materialize_skillopt_clean_test(
            clean_test, output_dir=output_dir / "native_split"
        )
        native_output = output_dir / "native_eval"
        command = [
            str(self.python),
            str(self.method_root / "scripts/eval_only.py"),
            "--config",
            str(self._config(benchmark)),
            "--skill",
            str(skill_path.resolve()),
            "--split",
            "test",
            "--optimizer_model",
            MODEL,
            "--target_model",
            MODEL,
            "--optimizer_backend",
            "openai_compatible",
            "--target_backend",
            "openai_compatible",
            "--split_dir",
            str(native_split),
            "--workers",
            str(self.budget.workers),
            "--test_env_num",
            str(len(clean_test)),
            "--max_turns",
            str(self.budget.max_turns),
            "--out_root",
            str(native_output),
            "--cfg-options",
            *self._common_options(benchmark, native_split),
        ]
        self._run(command, output_dir / "command")
        results_path = native_output / "results.jsonl"
        if not results_path.is_file():
            raise RuntimeError(f"SkillOpt produced no per-task results: {results_path}")
        per_task: dict[str, float] = {}
        result_rows: dict[str, dict[str, Any]] = {}
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            task_id = str(row.get("id") or row.get("task_id") or "")
            if task_id:
                per_task[task_id] = float(row.get("hard", 0))
                result_rows[task_id] = row
        expected = {task.task_id for task in clean_test}
        if set(per_task) != expected:
            raise RuntimeError(
                f"SkillOpt evaluation IDs differ: expected={sorted(expected)} "
                f"actual={sorted(per_task)}"
            )
        score = mean(per_task.values())
        category_counts = Counter(
            str(row.get("failure_category"))
            for row in result_rows.values()
            if str(row.get("failure_category") or "").strip()
        )
        systemic = {"provider_failure", "missing_oracle_page"}
        return EvaluationResult(
            score=score,
            per_task_scores=per_task,
            diagnostics={
                "stage": stage,
                "results_path": str(results_path),
                "exact_score": mean(
                    float(row.get("exact", row.get("hard", 0)))
                    for row in result_rows.values()
                ),
                "parseable_answer_rate": mean(
                    bool(str(row.get("predicted_answer") or "").strip())
                    for row in result_rows.values()
                ),
                "oracle_parsed_pages_rate": mean(
                    bool(row.get("oracle_parsed_pages_included", False))
                    for row in result_rows.values()
                ),
                "systemic_failure_rate": mean(
                    str(row.get("failure_category") or "") in systemic
                    for row in result_rows.values()
                ),
                "failure_category_counts": dict(sorted(category_counts.items())),
                "per_task_diagnostics": {
                    task_id: {
                        key: row.get(key)
                        for key in (
                            "exact",
                            "predicted_answer",
                            "failure_category",
                            "fail_reason",
                            "oracle_parsed_pages_included",
                            "oracle_parsed_pages_chars",
                            "agent_ok",
                            "n_turns",
                        )
                    }
                    for task_id, row in result_rows.items()
                },
            },
        )
