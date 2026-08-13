"""SkillAdaptor's native WebShop N3/N4 evidence boundary.

The public adapter deliberately uses SkillAdaptor's dataclass-shaped objects
without importing the external checkout. This keeps the benchmark package
installable on its own while still returning native ``Trajectory`` and
``LocalizedFault`` instances when the checkout calls the hook.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from rsebench.evidence import (
    EvidenceNoiseHook,
    EvidenceStage,
    FeedbackRecord,
    HookContext,
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
)
from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_contracts import EvolutionExecutionAudit
from rsebench.evolution.contracts import EvolutionArmManifest, EvolutionSplitManifest
from rsebench.evolution.runner import EvaluationResult, EvolutionArtifact
from rsebench.hashing import sha256_file
from rsebench.usage import token_context_environment


_ACTION_RE = re.compile(r"^\s*([a-zA-Z_]+)\[(.*)]\s*$")
_RESERVED_CLICKS = {
    "buy now",
    "next >",
    "< prev",
    "back to search",
    "search",
    "description",
    "features",
    "reviews",
}
MODEL = "deepseek-v4-flash"
_WALL_CLOCK_FIELDS = frozenset({"created_at", "updated_at", "timestamp"})


def canonicalize_skill_bank_artifact(path: Path | str) -> str:
    """Remove non-semantic clocks and return the persisted artifact hash."""

    artifact = Path(path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    def strip_clocks(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: strip_clocks(child)
                for key, child in value.items()
                if key not in _WALL_CLOCK_FIELDS
            }
        if isinstance(value, list):
            return [strip_clocks(child) for child in value]
        return value

    artifact.write_text(
        json.dumps(strip_clocks(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return sha256_file(artifact)


@dataclass(frozen=True)
class SkillAdaptorBudget:
    max_iterations: int = 1
    max_episode_steps: int = 8


def _execution_audit_from_report(
    report: dict[str, Any],
) -> EvolutionExecutionAudit:
    required = {
        "iterations",
        "final_skill_count",
        "accepted_update_count",
        "newly_adopted_skill_ids",
        "training_task_ids",
        "validation_task_ids",
    }
    missing = sorted(required - report.keys())
    if missing:
        raise RuntimeError(
            "SkillAdaptor report lacks execution-audit fields: "
            + ", ".join(missing)
        )
    return EvolutionExecutionAudit(
        train_task_ids=[str(value) for value in report["training_task_ids"]],
        validation_task_ids=[
            str(value) for value in report["validation_task_ids"]
        ],
        accepted_update_count=int(report["accepted_update_count"]),
        metadata={
            "iterations": int(report["iterations"]),
            "final_skill_count": int(report["final_skill_count"]),
            "newly_adopted_skill_ids": [
                str(value) for value in report["newly_adopted_skill_ids"]
            ],
        },
    )


def _goal_index(task_id: str, metadata: dict[str, Any] | None = None) -> int:
    value = (metadata or {}).get("goal_idx")
    if value is not None:
        return int(value)
    match = re.fullmatch(r"goal[_-](\d+)", task_id)
    if match is None:
        raise ValueError(f"WebShop task ID lacks goal index: {task_id}")
    return int(match.group(1))


def _action_tags(action: str, task_description: str) -> list[str]:
    match = _ACTION_RE.match(action)
    if match is None:
        return []
    verb, argument = match.group(1).casefold(), match.group(2).strip().casefold()
    if verb == "search":
        return ["query_refinement"]
    if verb != "click" or argument in _RESERVED_CLICKS:
        return []
    # Product identifiers are navigation, not option selection. WebShop ASINs
    # are ten alphanumeric characters and normally start with B0.
    if re.fullmatch(r"[a-z0-9]{10}", argument) and argument.startswith("b0"):
        return []
    goal = task_description.casefold()
    if argument and argument in goal:
        return ["required_option"]
    return []


class SkillAdaptorEvidenceAdapter:
    """Round-trip native SkillAdaptor records with step-level consistency."""

    def __init__(self, *, trajectory: Any | None = None) -> None:
        self.trajectory = trajectory

    def normalize_trajectory(
        self, native: Any, context: HookContext
    ) -> TrajectoryRecord:
        events = [
            TraceEvent(
                event_id=f"step-{position}",
                step_index=position,
                kind="action",
                action=str(step.action),
                observation=str(step.observation),
                tags=_action_tags(str(step.action), str(native.task_description)),
                metadata={
                    "native_position": position,
                    "native_step_index": int(step.index),
                },
            )
            for position, step in enumerate(native.steps)
        ]
        return TrajectoryRecord(
            task_id=str(native.task_id),
            benchmark=context.benchmark,
            events=events,
            reward=float(native.total_reward),
            success=bool(native.success),
            metadata={
                "method": "skilladaptor",
                "task_description": str(native.task_description),
            },
        )

    def denormalize_trajectory(
        self,
        native: Any,
        normalized: TrajectoryRecord,
        context: HookContext,
    ) -> Any:
        output = copy.deepcopy(native)
        retained_positions = [
            int(event.metadata["native_position"])
            for event in normalized.events
            if "native_position" in event.metadata
        ]
        output.steps = [copy.deepcopy(native.steps[pos]) for pos in retained_positions]
        for new_index, step in enumerate(output.steps):
            step.index = new_index
        if native.error_step is None:
            output.error_step = None
        elif native.error_step in retained_positions:
            output.error_step = retained_positions.index(native.error_step)
        else:
            output.error_step = None
        # The public N3 contract protects these fields. Assign from the
        # normalized record so a broken adapter cannot silently change them.
        output.total_reward = normalized.reward
        output.success = normalized.success
        return output

    def normalize_feedback(
        self, native: Any, context: HookContext
    ) -> FeedbackRecord:
        trajectory = self._require_trajectory()
        position = int(native.step_index)
        blamed = [f"step-{position}"] if 0 <= position < len(trajectory.steps) else []
        return FeedbackRecord(
            task_id=str(native.task_id),
            benchmark=context.benchmark,
            blamed_event_ids=blamed,
            diagnosis=str(native.improvement_principle),
            scalar_reward=float(trajectory.total_reward),
            metadata={
                "fault_type": getattr(native.fault_type, "value", str(native.fault_type)),
                "original_step_index": position,
            },
        )

    def denormalize_feedback(
        self,
        native: Any,
        normalized: FeedbackRecord,
        context: HookContext,
    ) -> Any:
        output = copy.deepcopy(native)
        if not normalized.blamed_event_ids:
            return output
        match = re.fullmatch(r"step-(\d+)", normalized.blamed_event_ids[0])
        if match is None:
            raise ValueError("SkillAdaptor N4 requires step-<position> event IDs")
        position = int(match.group(1))
        trajectory = self._require_trajectory()
        if position < 0 or position >= len(trajectory.steps):
            raise ValueError(f"SkillAdaptor N4 selected invalid step position: {position}")
        step = trajectory.steps[position]
        output.step_index = position
        output.observation = str(step.observation)
        output.wrong_action = str(step.action)
        output.skills_at_fault = list(step.skills_used)
        output.fault_chain = [position + 1]
        output.improvement_principle = normalized.diagnosis
        return output

    def _require_trajectory(self) -> Any:
        if self.trajectory is None:
            raise ValueError("SkillAdaptor feedback adaptation requires its trajectory")
        return self.trajectory


def mutate_skilladaptor_trajectory(
    trajectory: Any,
    *,
    spec: RuntimeNoiseSpec | None,
    context: HookContext,
) -> Any:
    if spec is None or spec.stage != EvidenceStage.trajectory:
        return trajectory
    hook = EvidenceNoiseHook(
        adapter=SkillAdaptorEvidenceAdapter(trajectory=trajectory),
        specs={EvidenceStage.trajectory: spec},
    )
    return hook.after_rollout(trajectory, context)


def mutate_skilladaptor_fault(
    fault: Any,
    trajectory: Any,
    *,
    spec: RuntimeNoiseSpec | None,
    context: HookContext,
) -> Any:
    if spec is None or spec.stage != EvidenceStage.feedback:
        return fault
    hook = EvidenceNoiseHook(
        adapter=SkillAdaptorEvidenceAdapter(trajectory=trajectory),
        specs={EvidenceStage.feedback: spec},
    )
    return hook.after_feedback(fault, trajectory, context)


def _spec_and_context(task_id: str) -> tuple[RuntimeNoiseSpec, HookContext] | None:
    spec_path = os.environ.get("RSEBENCH_EVIDENCE_SPEC", "").strip()
    if not spec_path:
        return None
    spec = RuntimeNoiseSpec.model_validate(
        json.loads(Path(spec_path).read_text(encoding="utf-8"))
    )
    audit_root = os.environ.get("RSEBENCH_EVIDENCE_AUDIT_ROOT", "").strip()
    if not audit_root:
        raise ValueError(
            "RSEBENCH_EVIDENCE_AUDIT_ROOT is required with RSEBENCH_EVIDENCE_SPEC"
        )
    context = HookContext(
        task_id=task_id,
        benchmark=spec.benchmark,
        domain=spec.domain,
        method="skilladaptor",
        arm=os.environ.get("RSEBENCH_EVIDENCE_ARM", "noisy"),
        run_dir=Path(audit_root),
    )
    return spec, context


def apply_skilladaptor_trajectory_from_env(trajectory: Any) -> Any:
    """External-checkout hook immediately after rollout, before Localizer."""

    configured = _spec_and_context(str(trajectory.task_id))
    if configured is None:
        return trajectory
    spec, context = configured
    return mutate_skilladaptor_trajectory(trajectory, spec=spec, context=context)


def apply_skilladaptor_fault_from_env(fault: Any, trajectory: Any) -> Any:
    """External-checkout hook after Localizer, before Linker/Reviser."""

    configured = _spec_and_context(str(trajectory.task_id))
    if configured is None:
        return fault
    spec, context = configured
    return mutate_skilladaptor_fault(
        fault, trajectory, spec=spec, context=context
    )


class SkillAdaptorExecutor:
    """Subprocess wrapper around the pinned SkillAdaptor WebShop runner."""

    def __init__(
        self,
        *,
        method_root: Path | str,
        webshop_root: Path | str,
        project_root: Path | str,
        budget: SkillAdaptorBudget | None = None,
        command_runner: Callable[..., Any] = subprocess.run,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.method_root = Path(method_root).resolve()
        self.webshop_root = Path(webshop_root).resolve()
        self.project_root = Path(project_root).resolve()
        self.budget = budget or SkillAdaptorBudget()
        self.command_runner = command_runner
        if environment is None:
            from scripts.baselines.common_env import combined_method_env

            environment = combined_method_env("skilladaptor")
        self.environment = dict(environment)
        inherited = self.environment.get("PYTHONPATH", "").strip()
        pythonpath = [str(self.project_root), str(self.project_root / "src")]
        if inherited:
            pythonpath.append(inherited)
        self.environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
        self.environment["WEBSHOP_PATH"] = str(self.webshop_root)
        self.environment["SkillAdaptor_LEXICAL_MATCHING"] = "1"
        self.environment["SkillAdaptor_LEXICAL_SKILL_THRESHOLD"] = "0.10"
        webshop_python = self.webshop_root / ".venv/bin/python"
        self.python = str(webshop_python) if webshop_python.is_file() else sys.executable
        self._token_run_dir: Path | None = None

    def configure_token_run(
        self, run_dir: Path | str, *, default_arm: str | None = None
    ) -> None:
        del default_arm
        self._token_run_dir = Path(run_dir).resolve()

    def _token_environment(self, *, arm: str, stage: str) -> dict[str, str]:
        if self._token_run_dir is None:
            return dict(self.environment)
        return token_context_environment(
            self.environment,
            ledger_dir=self._token_run_dir / "token_usage",
            run_id=self._token_run_dir.name,
            domain="interactive",
            benchmark="webshop",
            arm=arm,
            stage=stage,
        )

    def _run(
        self,
        command: list[str],
        record_dir: Path,
        *,
        environment: dict[str, str],
    ) -> None:
        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / "command.json").write_text(
            json.dumps(command, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        completed = self.command_runner(
            command,
            cwd=self.method_root,
            env=environment,
            capture_output=True,
            text=True,
        )
        secret = self.environment.get("DEEPSEEK_API_KEY", "").strip()

        def redact(text: str) -> str:
            return text.replace(secret, "[REDACTED]") if secret else text

        (record_dir / "stdout.log").write_text(
            redact(str(completed.stdout or "")), encoding="utf-8"
        )
        (record_dir / "stderr.log").write_text(
            redact(str(completed.stderr or "")), encoding="utf-8"
        )
        if completed.returncode != 0:
            tail = redact(str(completed.stderr or completed.stdout or ""))[-2000:]
            raise RuntimeError(
                f"SkillAdaptor command failed with exit {completed.returncode}: {tail}"
            )

    @staticmethod
    def _tasks_for_arm(
        pairs: list[Any], arm: str
    ) -> list[TaskManifest]:
        return [pair.clean if arm == "clean" else pair.noisy for pair in pairs]

    @staticmethod
    def _manifest_payload(
        train: list[TaskManifest],
        validation: list[TaskManifest],
        test: list[TaskManifest],
    ) -> dict[str, list[int]]:
        return {
            "input_tasks": [
                _goal_index(task.task_id, task.metadata) for task in train
            ],
            "validation_tasks": [
                _goal_index(task.task_id, task.metadata) for task in validation
            ],
            "test_tasks": [
                _goal_index(task.task_id, task.metadata) for task in test
            ],
        }

    def evolve(
        self,
        *,
        arm: EvolutionArmManifest,
        split: EvolutionSplitManifest,
        seed_skill_path: Path,
        output_dir: Path,
    ) -> EvolutionArtifact:
        output_dir = Path(output_dir).resolve()
        train = self._tasks_for_arm(split.train, arm.arm)
        validation = self._tasks_for_arm(split.validation, arm.arm)
        task_manifest = output_dir / "webshop_task_manifest.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        task_manifest.write_text(
            json.dumps(
                # The paired runner evaluates the frozen bank on the untouched
                # clean split.  Keep test goals out of the native evolution
                # subprocess to avoid a redundant, costly pre-evaluation.
                self._manifest_payload(train, validation, []),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        native_output = output_dir / "native_train"
        environment = self._token_environment(arm=arm.arm, stage="evolution")
        environment["RSEBENCH_SKILL_RETRIEVAL_AUDIT"] = str(
            (output_dir / "retrieval_audit" / f"{arm.arm}_evolution.jsonl").resolve()
        )
        # SkillAdaptor defaults to five validation samples.  Core-1's bounded
        # pilot uses one (smoke) or three (efficacy), so retaining the default
        # would make skill adoption impossible by construction.
        environment["SkillAdaptor_MIN_SAMPLE_SIZE"] = str(
            max(1, len(validation))
        )
        stage = str(arm.parameters.get("stage") or "")
        if arm.arm == "noisy" and stage in {"N3", "N4"}:
            spec = (
                self.project_root
                / "benchmark"
                / "core1"
                / "runtime"
                / "webshop"
                / f"{stage}.json"
            )
            if not spec.is_file():
                raise FileNotFoundError(f"WebShop runtime evidence spec missing: {spec}")
            environment.update(
                {
                    "RSEBENCH_EVIDENCE_SPEC": str(spec),
                    "RSEBENCH_EVIDENCE_AUDIT_ROOT": str(output_dir),
                    "RSEBENCH_EVIDENCE_ARM": arm.arm,
                }
            )
        elif arm.arm == "noisy" and stage in {"N1", "N2"}:
            static_path = Path(
                str(arm.parameters.get("static_noise_path") or "")
            )
            if not static_path.is_file():
                raise FileNotFoundError(
                    "WebShop N1/N2 requires parameters.static_noise_path"
                )
            environment["RSEBENCH_WEBSHOP_STATIC_NOISE"] = str(
                static_path.resolve()
            )
        command = [
            self.python,
            str(self.method_root / "run_skill_adaptor.py"),
            "--env",
            "webshop",
            "--provider",
            "deepseek",
            "--model",
            MODEL,
            "--max-iterations",
            str(self.budget.max_iterations),
            "--max-episode-steps",
            str(self.budget.max_episode_steps),
            "--skip-held-out-test",
            "--task-manifest",
            str(task_manifest),
            "--skills",
            str(seed_skill_path.resolve()),
            "--output",
            str(native_output),
        ]
        self._run(command, output_dir / "command", environment=environment)
        artifact = native_output / "skill_bank_final.json"
        if not artifact.is_file():
            raise RuntimeError(f"SkillAdaptor produced no skill bank: {artifact}")
        artifact_hash = canonicalize_skill_bank_artifact(artifact)
        diagnostics: dict[str, Any] = {}
        report = native_output / "SkillAdaptor_report.json"
        if not report.is_file():
            raise RuntimeError(f"SkillAdaptor produced no native report: {report}")
        report_payload = json.loads(report.read_text(encoding="utf-8"))
        diagnostics["report"] = report_payload
        return EvolutionArtifact(
            skill_path=str(artifact.resolve()),
            skill_hash=artifact_hash,
            diagnostics=diagnostics,
            execution_audit=_execution_audit_from_report(report_payload),
        )

    def evaluate(
        self,
        *,
        skill_path: Path,
        clean_test: list[TaskManifest],
        output_dir: Path,
        stage: str,
    ) -> EvaluationResult:
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        task_manifest = output_dir / "webshop_task_manifest.json"
        task_manifest.write_text(
            json.dumps(
                self._manifest_payload([], [], clean_test),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        result_path = output_dir / "result.json"
        script = self.project_root / "scripts" / "eval_skilladaptor_webshop.py"
        command = [
            self.python,
            str(script),
            "--method-root",
            str(self.method_root),
            "--webshop-root",
            str(self.webshop_root),
            "--manifest",
            str(task_manifest),
            "--skills",
            str(skill_path.resolve()),
            "--max-episode-steps",
            str(self.budget.max_episode_steps),
            "--output",
            str(result_path),
        ]
        environment = self._token_environment(arm=stage, stage="eval")
        environment["RSEBENCH_SKILL_RETRIEVAL_AUDIT"] = str(
            (output_dir / "retrieval_audit" / f"{stage}_test.jsonl").resolve()
        )
        for key in (
            "RSEBENCH_EVIDENCE_SPEC",
            "RSEBENCH_EVIDENCE_AUDIT_ROOT",
            "RSEBENCH_EVIDENCE_ARM",
            "RSEBENCH_WEBSHOP_STATIC_NOISE",
        ):
            environment.pop(key, None)
        self._run(command, output_dir / "command", environment=environment)
        if not result_path.is_file():
            raise RuntimeError(f"SkillAdaptor evaluation produced no result: {result_path}")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        return EvaluationResult.model_validate(payload)
