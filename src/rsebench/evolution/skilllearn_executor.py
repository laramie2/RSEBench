"""Separated-round SkillLearnBench executor for DeepSeek API evolution."""

from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evidence import (
    EvidenceNoiseHook,
    EvidenceStage,
    FeedbackRecord,
    HookContext,
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
)
from rsebench.evolution.contracts import EvolutionArmManifest, EvolutionSplitManifest
from rsebench.evolution.clean_contracts import EvolutionExecutionAudit
from rsebench.evolution.runner import EvaluationResult, EvolutionArtifact
from rsebench.experiments.timing import TimingRecorder
from rsebench.hashing import sha256_file, sha256_tree
from rsebench.usage import token_context_scope


_DOCKER_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Run a shell command inside the isolated task container at its "
                "working directory. Use it to inspect inputs and create outputs."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }
]


def _tool_argument_recovery_prompt(error: Exception) -> str | None:
    """Return a narrow retry instruction for malformed provider tool JSON."""

    if "returned invalid JSON arguments" not in str(error):
        return None
    return (
        "Your previous tool call arguments were malformed JSON. Retry the same "
        "step with one short single-line command and a valid JSON object. Do "
        "not combine multiple shell programs into one tool call."
    )


def _command_tags(command: str) -> list[str]:
    """Classify shell evidence without treating every Python read as a write."""

    lower = command.casefold()
    tags: set[str] = set()
    write_markers = (
        "wb.save(",
        ".save(",
        "write_text(",
        "write_bytes(",
        ".to_csv(",
        ".to_excel(",
        "json.dump(",
        "yaml.dump(",
        "shutil.copy",
        " cp ",
        "mv ",
        "mkdir",
        "touch ",
        "tee ",
        "convert ",
        "ffmpeg",
    )
    writes_with_open = bool(
        re.search(r"open\([^\n]{0,240},\s*['\"][wax+]", lower)
    )
    shell_redirection = bool(
        re.search(r"(?:^|[;|&]\s*|\s)>{1,2}\s*(?!/?dev/null\b)", lower)
    )
    if any(marker in lower for marker in write_markers) or writes_with_open or shell_redirection:
        tags.update({"filesystem_change", "artifact_write"})
    if any(
        marker in lower
        for marker in (
            "cat ",
            "head ",
            "sed ",
            "ls ",
            "find ",
            "read_text(",
            "load_workbook(",
        )
    ):
        tags.add("input_read")
    return sorted(tags)


def _docker_volume_spec(host: Path | str, container: str) -> str:
    """Render an absolute host bind mount for the Docker CLI."""

    return f"{Path(host).resolve()}:{container}"


class SkillLearnExecution(StrictModel):
    task_id: str = Field(min_length=1)
    reward: float
    success: bool
    events: list[TraceEvent]
    directional_failure: str = ""
    hidden_verifier_detail: str = ""
    blamed_event_ids: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SkillLearnImageRecord(StrictModel):
    task_id: str = Field(min_length=1)
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_tag: str = Field(min_length=1)
    image_id: str = Field(min_length=1)
    workdir: str = Field(min_length=1)


class SkillLearnBackend(Protocol):
    def execute(
        self,
        task: TaskManifest,
        skill: str,
        output_dir: Path,
    ) -> SkillLearnExecution: ...

    def evaluate(
        self,
        task: TaskManifest,
        skill: str,
        output_dir: Path,
    ) -> float: ...


class DockerSkillLearnBackend:
    """Run DeepSeek's tool loop in the official SkillLearnBench container.

    Model calls stay on the host through the shared DeepSeek client. Only tool
    commands run inside the task container, so no CLI-provider substitution is
    involved and token accounting remains observable.
    """

    def __init__(
        self,
        *,
        client: Any,
        docker: str = "docker",
        max_turns: int = 16,
        command_timeout: int = 300,
        require_prebuilt: bool = False,
    ) -> None:
        self.client = client
        self.docker = docker
        self.max_turns = max_turns
        self.command_timeout = command_timeout
        self.require_prebuilt = require_prebuilt

    @staticmethod
    def _workdir(dockerfile: Path) -> str:
        workdir = "/root"
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("WORKDIR "):
                candidate = stripped.split(None, 1)[1].strip()
                if candidate.startswith("/") and "$" not in candidate:
                    workdir = candidate
        return workdir

    @staticmethod
    def _tag(command: str) -> list[str]:
        return _command_tags(command)

    def prepare(
        self,
        task: TaskManifest,
        output_dir: Path,
    ) -> SkillLearnImageRecord:
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        instance = Path(task.artifact_path or "").resolve()
        environment = instance / "environment"
        dockerfile = environment / "Dockerfile"
        if not dockerfile.is_file():
            raise FileNotFoundError(f"SkillLearn Dockerfile missing: {dockerfile}")
        with tempfile.TemporaryDirectory(prefix="rsebench-skilllearn-build-") as temp:
            context = Path(temp) / "environment"
            shutil.copytree(
                environment,
                context,
                ignore=shutil.ignore_patterns("skills"),
            )
            (context / "skills").mkdir(exist_ok=True)
            context_hash = sha256_tree(context)
            image = f"rsebench-skilllearn:{context_hash[:16]}"
            inspect = subprocess.run(
                [self.docker, "image", "inspect", "--format={{.Id}}", image],
                capture_output=True,
                text=True,
            )
            if inspect.returncode != 0:
                if self.require_prebuilt:
                    raise RuntimeError(
                        f"prebuilt SkillLearn image is missing: {image}"
                    )
                built = subprocess.run(
                    [self.docker, "build", "-t", image, str(context)],
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                (output_dir / "docker_build.log").write_text(
                    (built.stdout or "") + (built.stderr or ""), encoding="utf-8"
                )
                if built.returncode != 0:
                    raise RuntimeError(
                        f"SkillLearn image build failed: {(built.stderr or built.stdout)[-2000:]}"
                    )
                inspect = subprocess.run(
                    [self.docker, "image", "inspect", "--format={{.Id}}", image],
                    capture_output=True,
                    text=True,
                )
            if inspect.returncode != 0 or not str(inspect.stdout or "").strip():
                raise RuntimeError(f"SkillLearn image inspect failed after build: {image}")
            record = SkillLearnImageRecord(
                task_id=task.task_id,
                context_hash=context_hash,
                image_tag=image,
                image_id=str(inspect.stdout).strip(),
                workdir=self._workdir(context / "Dockerfile"),
            )
        (output_dir / "image_record.json").write_text(
            record.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return record

    def execute(
        self,
        task: TaskManifest,
        skill: str,
        output_dir: Path,
    ) -> SkillLearnExecution:
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        instance = Path(task.artifact_path or "").resolve()
        official = Path(task.metadata.get("official_instance_path") or instance).resolve()
        tests = official / "tests"
        if not tests.is_dir():
            raise FileNotFoundError(f"SkillLearn official tests missing: {tests}")
        image_record = self.prepare(task, output_dir / "image")
        image = image_record.image_tag
        workdir = image_record.workdir
        container_hash = hashlib.sha256(
            f"{task.task_id}:{output_dir.resolve()}".encode()
        ).hexdigest()[:16]
        container = f"rsebench-skilllearn-{container_hash}"
        subprocess.run(
            [self.docker, "rm", "-f", container], capture_output=True, text=True
        )
        (output_dir / "verifier").mkdir(exist_ok=True)
        started = subprocess.run(
            [
                self.docker,
                "run",
                "-d",
                "--name",
                container,
                "-v",
                _docker_volume_spec(tests, "/tests:ro"),
                "-v",
                _docker_volume_spec(output_dir, "/logs"),
                image,
                "sleep",
                "3600",
            ],
            capture_output=True,
            text=True,
        )
        if started.returncode != 0:
            raise RuntimeError(f"SkillLearn container failed: {started.stderr[-2000:]}")
        events: list[TraceEvent] = []
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are executing a SkillLearnBench task in an isolated Linux "
                    "container. Use run_shell to inspect the workspace and create every "
                    "requested artifact. Do not discuss a plan instead of executing it.\n\n"
                    f"Reusable skill:\n{skill}"
                ),
            },
            {"role": "user", "content": task.prompt},
        ]
        final_text = ""
        tool_argument_retries = 0
        artifact_retries = 0
        try:
            for turn in range(self.max_turns):
                try:
                    response = self.client.complete(
                        messages,
                        tools=_DOCKER_TOOL,
                        tool_choice="auto",
                        role="skilllearn_executor",
                    )
                except RuntimeError as exc:
                    recovery = _tool_argument_recovery_prompt(exc)
                    if recovery is None or tool_argument_retries >= 2:
                        raise
                    tool_argument_retries += 1
                    messages.append({"role": "user", "content": recovery})
                    events.append(
                        TraceEvent(
                            event_id=f"protocol-recovery-{tool_argument_retries}",
                            step_index=len(events),
                            kind="message",
                            observation=recovery,
                            tags=["provider_protocol_recovery"],
                            metadata={"protected": True},
                        )
                    )
                    continue
                if not response.tool_calls:
                    wrote_artifact = any(
                        "artifact_write" in event.tags for event in events
                    )
                    if not wrote_artifact and artifact_retries < 2:
                        artifact_retries += 1
                        recovery = (
                            "You have inspected the workspace but have not executed an "
                            "artifact-producing command. Perform the requested changes "
                            "inside the container and save the required output now; do "
                            "not return another plan."
                        )
                        messages.append({"role": "user", "content": recovery})
                        events.append(
                            TraceEvent(
                                event_id=f"artifact-recovery-{artifact_retries}",
                                step_index=len(events),
                                kind="message",
                                observation=recovery,
                                tags=["execution_recovery"],
                                metadata={"protected": True},
                            )
                        )
                        continue
                    final_text = response.content
                    break
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or None,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.arguments),
                                },
                            }
                            for call in response.tool_calls
                        ],
                    }
                )
                for call in response.tool_calls:
                    if call.name != "run_shell":
                        observation = f"tool_error: unsupported tool {call.name}"
                        command = call.name
                    else:
                        command = str(call.arguments.get("command") or "")
                        completed = subprocess.run(
                            [
                                self.docker,
                                "exec",
                                "-w",
                                workdir,
                                container,
                                "sh",
                                "-lc",
                                command,
                            ],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=self.command_timeout,
                        )
                        observation = (completed.stdout or "") + (completed.stderr or "")
                        if completed.returncode:
                            observation += f"\n[exit_code={completed.returncode}]"
                        observation = observation[-12000:]
                    event_id = f"tool-{len(events)}"
                    events.append(
                        TraceEvent(
                            event_id=event_id,
                            step_index=len(events),
                            kind="tool",
                            action=command,
                            observation=observation or "command completed without output",
                            tags=self._tag(command),
                        )
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": observation,
                        }
                    )
            else:
                final_text = f"max_turns={self.max_turns} reached"

            verifier = subprocess.run(
                [self.docker, "exec", container, "bash", "/tests/test.sh"],
                capture_output=True,
                text=True,
                timeout=600,
            )
            hidden = ((verifier.stdout or "") + (verifier.stderr or ""))[-12000:]
            reward_path = output_dir / "verifier" / "reward.txt"
            if reward_path.is_file():
                try:
                    reward = float(reward_path.read_text(encoding="utf-8").strip())
                except ValueError:
                    reward = float(verifier.returncode == 0)
            else:
                reward = float(verifier.returncode == 0)
            success = reward >= 1.0
            blamed = next(
                (
                    [event.event_id]
                    for event in reversed(events)
                    if "filesystem_change" in event.tags
                ),
                [events[-1].event_id] if events else [],
            )
            (output_dir / "agent_final.txt").write_text(final_text, encoding="utf-8")
            (output_dir / "trajectory.json").write_text(
                json.dumps(
                    [event.model_dump(mode="json") for event in events],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            return SkillLearnExecution(
                task_id=task.task_id,
                reward=reward,
                success=success,
                events=events,
                directional_failure=(
                    "" if success else "The official artifact verifier did not pass."
                ),
                hidden_verifier_detail=hidden,
                blamed_event_ids=blamed,
                diagnostics={
                    "container": container,
                    "image": image,
                    "image_id": image_record.image_id,
                    "context_hash": image_record.context_hash,
                    "verifier_returncode": verifier.returncode,
                },
            )
        finally:
            subprocess.run(
                [self.docker, "rm", "-f", container],
                capture_output=True,
                text=True,
            )

    def evaluate(
        self,
        task: TaskManifest,
        skill: str,
        output_dir: Path,
    ) -> float:
        return self.execute(task, skill, output_dir).reward


class _NormalizedAdapter:
    def normalize_trajectory(
        self, native: TrajectoryRecord, context: HookContext
    ) -> TrajectoryRecord:
        return native

    def denormalize_trajectory(
        self,
        native: TrajectoryRecord,
        normalized: TrajectoryRecord,
        context: HookContext,
    ) -> TrajectoryRecord:
        return normalized

    def normalize_feedback(
        self, native: FeedbackRecord, context: HookContext
    ) -> FeedbackRecord:
        return native

    def denormalize_feedback(
        self,
        native: FeedbackRecord,
        normalized: FeedbackRecord,
        context: HookContext,
    ) -> FeedbackRecord:
        return normalized


class SkillLearnExecutor:
    def __init__(
        self,
        *,
        client: Any,
        backend: SkillLearnBackend,
        evidence_spec: RuntimeNoiseSpec | None,
        feedback_mode: Literal["self", "teacher"] = "self",
        ledger_dir: str | Path,
        run_id: str,
    ) -> None:
        self.client = client
        self.backend = backend
        self.evidence_spec = evidence_spec
        self.feedback_mode = feedback_mode
        self.ledger_dir = Path(ledger_dir)
        self.run_id = run_id
        self._timing_recorder: TimingRecorder | None = None

    def configure_token_run(
        self, run_dir: str | Path, *, default_arm: str | None = None
    ) -> None:
        root = Path(run_dir).resolve()
        self.ledger_dir = root / "token_usage"
        self.run_id = root.name

    def configure_timing(self, recorder: TimingRecorder) -> None:
        self._timing_recorder = recorder

    def _task_span(self, *, name: str, task_id: str):
        if self._timing_recorder is None:
            return nullcontext()
        return self._timing_recorder.span(
            level="task", name=name, task_id=task_id
        )

    def _context(self, task: TaskManifest, arm: str, output_dir: Path) -> HookContext:
        return HookContext(
            task_id=task.task_id,
            benchmark=task.benchmark,
            domain=task.domain,
            method=(
                "skilllearn_teacher_feedback"
                if self.feedback_mode == "teacher"
                else "skilllearn_self_feedback"
            ),
            arm=arm,
            run_dir=output_dir,
        )

    def _complete(
        self,
        *,
        task: TaskManifest,
        arm: str,
        stage: str,
        role: str,
        system: str,
        user: str,
    ) -> str:
        with token_context_scope(
            ledger_dir=self.ledger_dir,
            run_id=self.run_id,
            domain=task.domain,
            benchmark=task.benchmark,
            arm=arm,
            stage=stage,
        ):
            response = self.client.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                role=role,
            )
        return str(response.content).strip()

    @staticmethod
    def _trajectory(task: TaskManifest, execution: SkillLearnExecution) -> TrajectoryRecord:
        return TrajectoryRecord(
            task_id=task.task_id,
            benchmark=task.benchmark,
            events=execution.events,
            reward=execution.reward,
            success=execution.success,
            metadata={"task_family": task.metadata.get("task_family", "")},
        )

    def run_evolution_round(
        self,
        *,
        task: TaskManifest,
        skill: str,
        arm: Literal["clean", "noisy"],
        output_dir: str | Path,
    ) -> str:
        with self._task_span(name="evolution", task_id=task.task_id):
            return self._run_evolution_round_impl(
                task=task,
                skill=skill,
                arm=arm,
                output_dir=output_dir,
            )

    def _run_evolution_round_impl(
        self,
        *,
        task: TaskManifest,
        skill: str,
        arm: Literal["clean", "noisy"],
        output_dir: str | Path,
    ) -> str:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        with token_context_scope(
            ledger_dir=self.ledger_dir,
            run_id=self.run_id,
            domain=task.domain,
            benchmark=task.benchmark,
            arm=arm,
            stage="skilllearn_execution",
        ):
            execution = self.backend.execute(task, skill, root / "execution")
        trajectory = self._trajectory(task, execution)
        context = self._context(task, arm, root)
        visible_trajectory = trajectory
        if (
            arm == "noisy"
            and self.evidence_spec is not None
            and self.evidence_spec.stage == EvidenceStage.trajectory
        ):
            hook = EvidenceNoiseHook(
                adapter=_NormalizedAdapter(),
                specs={EvidenceStage.trajectory: self.evidence_spec},
            )
            visible_trajectory = hook.after_rollout(trajectory, context)

        trajectory_text = json.dumps(
            visible_trajectory.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        if self.feedback_mode == "teacher":
            feedback_text = self._complete(
                task=task,
                arm=arm,
                stage="skilllearn_teacher_feedback",
                role="skilllearn_teacher",
                system=(
                    "Give concise directional skill-improvement advice. Do not "
                    "provide a solution, gold skill, hidden test, or verifier output."
                ),
                user=(
                    f"Task:\n{task.prompt}\n\nCurrent skill:\n{skill}\n\n"
                    f"Visible trajectory:\n{trajectory_text}\n\n"
                    f"Directional failure:\n{execution.directional_failure}"
                ),
            )
        else:
            feedback_text = self._complete(
                task=task,
                arm=arm,
                stage="skilllearn_self_feedback",
                role="skilllearn_self_reflector",
                system=(
                    "Diagnose reusable skill gaps only from the task and visible "
                    "trajectory. Do not assume access to hidden tests or a reference solution."
                ),
                user=(
                    f"Task:\n{task.prompt}\n\nCurrent skill:\n{skill}\n\n"
                    f"Outcome: {'success' if execution.success else 'unsuccessful'}\n\n"
                    f"Visible trajectory:\n{trajectory_text}"
                ),
            )

        feedback = FeedbackRecord(
            task_id=task.task_id,
            benchmark=task.benchmark,
            blamed_event_ids=execution.blamed_event_ids,
            diagnosis=feedback_text,
            recommendation=feedback_text,
            scalar_reward=execution.reward,
        )
        visible_feedback = feedback
        if (
            arm == "noisy"
            and self.evidence_spec is not None
            and self.evidence_spec.stage == EvidenceStage.feedback
        ):
            hook = EvidenceNoiseHook(
                adapter=_NormalizedAdapter(),
                specs={EvidenceStage.feedback: self.evidence_spec},
            )
            visible_feedback = hook.after_feedback(feedback, trajectory, context)

        rewrite_prompt = (
            f"Task:\n{task.prompt}\n\nCurrent skill:\n{skill}\n\n"
            f"Revision diagnosis:\n{visible_feedback.diagnosis}\n\n"
            "Return the complete revised reusable skill in Markdown."
        )
        revised = self._complete(
            task=task,
            arm=arm,
            stage="skilllearn_skill_rewrite",
            role="skilllearn_skill_reviser",
            system=(
                "Rewrite the reusable skill using the supplied diagnosis. Do not "
                "include hidden verifier details or a task-specific final answer."
            ),
            user=rewrite_prompt,
        )
        (root / "visible_trajectory.json").write_text(
            json.dumps(
                visible_trajectory.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "visible_feedback.json").write_text(
            visible_feedback.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (root / "revised_skill.md").write_text(revised + "\n", encoding="utf-8")
        return revised

    def evaluate_task(
        self,
        *,
        task: TaskManifest,
        skill: str,
        output_dir: str | Path,
        arm: str,
        usage_stage: str = "skilllearn_clean_test_execution",
    ) -> float:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        with self._task_span(name=usage_stage, task_id=task.task_id):
            with token_context_scope(
                ledger_dir=self.ledger_dir,
                run_id=self.run_id,
                domain=task.domain,
                benchmark=task.benchmark,
                arm=arm,
                stage=usage_stage,
            ):
                return float(self.backend.evaluate(task, skill, destination))

    def _validation_score(
        self,
        *,
        tasks: list[TaskManifest],
        skill: str,
        output_dir: Path,
        arm: str,
    ) -> float:
        scores = [
            self.evaluate_task(
                task=task,
                skill=skill,
                output_dir=output_dir / task.task_id,
                arm=arm,
                usage_stage="skilllearn_validation_execution",
            )
            for task in tasks
        ]
        return sum(scores) / len(scores) if scores else 0.0

    def evolve(
        self,
        *,
        arm: EvolutionArmManifest,
        split: EvolutionSplitManifest,
        seed_skill_path: Path,
        output_dir: Path,
    ) -> EvolutionArtifact:
        skill = seed_skill_path.read_text(encoding="utf-8")
        by_id = {pair.task_id: pair for pair in split.train}
        validation_by_id = {pair.task_id: pair for pair in split.validation}
        validation_tasks = [
            getattr(validation_by_id[task_ref.task_id], arm.arm)
            for task_ref in arm.validation
        ]
        rounds: list[str] = []
        completed_train_ids: list[str] = []
        completed_validation_ids: set[str] = set()
        validation_records: list[dict[str, Any]] = []
        validation_score = (
            self._validation_score(
                tasks=validation_tasks,
                skill=skill,
                output_dir=output_dir / "validation" / "seed",
                arm=arm.arm,
            )
            if validation_tasks
            else None
        )
        if validation_tasks:
            completed_validation_ids.update(task.task_id for task in validation_tasks)
        validation_seed_score = validation_score
        for index, task_ref in enumerate(arm.train, start=1):
            pair = by_id[task_ref.task_id]
            task = getattr(pair, arm.arm)
            round_dir = output_dir / "evolution" / f"round-{index}-{task.task_id}"
            candidate = self.run_evolution_round(
                task=task,
                skill=skill,
                arm=arm.arm,
                output_dir=round_dir,
            )
            completed_train_ids.append(task.task_id)
            if validation_tasks:
                candidate_score = self._validation_score(
                    tasks=validation_tasks,
                    skill=candidate,
                    output_dir=output_dir / "validation" / f"round-{index}",
                    arm=arm.arm,
                )
                accepted = bool(candidate_score >= float(validation_score))
                record = {
                    "round": index,
                    "task_id": task.task_id,
                    "incumbent_score": validation_score,
                    "candidate_score": candidate_score,
                    "accepted": accepted,
                }
                (round_dir / "acceptance.json").write_text(
                    json.dumps(record, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                validation_records.append(record)
                if accepted:
                    skill = candidate
                    validation_score = candidate_score
            else:
                skill = candidate
            rounds.append(str(round_dir))
        skill_path = output_dir / "evolved_skill.md"
        skill_path.write_text(skill.rstrip() + "\n", encoding="utf-8")
        return EvolutionArtifact(
            skill_path=str(skill_path),
            skill_hash=sha256_file(skill_path),
            diagnostics={
                "rounds": rounds,
                "feedback_mode": self.feedback_mode,
                "validation_seed_score": validation_seed_score,
                "validation_final_score": validation_score,
                "validation": validation_records,
            },
            execution_audit=EvolutionExecutionAudit(
                train_task_ids=completed_train_ids,
                validation_task_ids=sorted(completed_validation_ids),
                accepted_update_count=sum(
                    bool(row["accepted"]) for row in validation_records
                ),
                metadata={
                    "round_count": len(rounds),
                    "validation_evaluation_count": len(validation_tasks)
                    * (1 + len(validation_records)),
                    "validation_seed_score": validation_seed_score,
                    "validation_final_score": validation_score,
                },
            ),
        )

    def evaluate(
        self,
        *,
        skill_path: Path,
        clean_test: list[TaskManifest],
        output_dir: Path,
        stage: str,
    ) -> EvaluationResult:
        skill = skill_path.read_text(encoding="utf-8")
        scores: dict[str, float] = {}
        for task in clean_test:
            scores[task.task_id] = self.evaluate_task(
                task=task,
                skill=skill,
                output_dir=output_dir / task.task_id,
                arm=stage if stage in {"clean", "noisy"} else "seed",
            )
        score = sum(scores.values()) / len(scores) if scores else 0.0
        return EvaluationResult(
            score=score,
            per_task_scores=scores,
            diagnostics={"stage": stage, "task_count": len(scores)},
        )
