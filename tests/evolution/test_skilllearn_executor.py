from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from rsebench.contracts import TaskManifest
from rsebench.contracts import NoiseManifest, Severity
from rsebench.evidence import RuntimeNoiseSpec, TraceEvent
from rsebench.evolution.contracts import EvolutionSplitManifest, EvolutionTaskPair
from rsebench.evolution.pairs import build_arm_manifests
from rsebench.evolution.skilllearn_executor import (
    _command_tags,
    _container_runtime_identity,
    _docker_volume_spec,
    _tool_argument_recovery_prompt,
    DockerSkillLearnBackend,
    SkillLearnExecution,
    SkillLearnExecutor,
)
import rsebench.evolution.skilllearn_executor as skilllearn_module
from rsebench.providers.deepseek import ModelResponse
from rsebench.hashing import sha256_file


class ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def complete(self, messages, *, role: str, **kwargs) -> ModelResponse:
        self.calls.append(
            {
                "messages": messages,
                "role": role,
                "arm": os.environ.get("RSEBENCH_TOKEN_ARM"),
                "stage": os.environ.get("RSEBENCH_TOKEN_STAGE"),
            }
        )
        return ModelResponse(content=self.responses.pop(0))


class FakeBackend:
    hidden = "SECRET VERIFIER: copy the gold implementation"

    def __init__(self) -> None:
        self.skills: list[str] = []

    def execute(self, task: TaskManifest, skill: str, output_dir: Path) -> SkillLearnExecution:
        self.skills.append(skill)
        return SkillLearnExecution(
            task_id=task.task_id,
            reward=0.0,
            success=False,
            events=[
                TraceEvent(
                    event_id="e0",
                    step_index=0,
                    kind="tool",
                    action="read input.txt",
                    observation="input data",
                    tags=["input_read"],
                ),
                TraceEvent(
                    event_id="e1",
                    step_index=1,
                    kind="tool",
                    action="write output.txt",
                    observation="wrote output.txt",
                    tags=["filesystem_change", "artifact_write"],
                ),
                TraceEvent(
                    event_id="e2",
                    step_index=2,
                    kind="tool",
                    action="inspect output.txt",
                    observation="wrong layout",
                    tags=["inspection"],
                ),
            ],
            directional_failure="The generated artifact has the wrong layout.",
            hidden_verifier_detail=self.hidden,
            blamed_event_ids=["e1"],
        )

    def evaluate(self, task: TaskManifest, skill: str, output_dir: Path) -> float:
        self.skills.append(skill)
        return 1.0 if "revised" in skill else 0.0


def task(tmp_path: Path) -> TaskManifest:
    instance = tmp_path / "family-1"
    instance.mkdir()
    return TaskManifest(
        task_id="family-1",
        benchmark="skilllearnbench",
        domain="skill_learning",
        prompt="Create the requested artifact.",
        source_hash="a" * 64,
        artifact_path=str(instance),
        verifier="official:/tests/test.sh",
        metadata={"task_family": "family"},
    )


def _evolution_pair(item: TaskManifest) -> EvolutionTaskPair:
    noisy = item.model_copy(update={"source_hash": "b" * 64})
    return EvolutionTaskPair(
        pair_id=f"pair-{item.task_id}",
        task_id=item.task_id,
        clean=item,
        noisy=noisy,
        noise=NoiseManifest(
            noise_id=f"noise-{item.task_id}",
            task_id=item.task_id,
            channel="C1",
            mechanism="M1",
            operator="fixture",
            domain="skill_learning",
            benchmark="skilllearnbench",
            severity=Severity(level="L1", budget=1),
            seed=1,
            clean_hash=item.source_hash,
            noisy_hash=noisy.source_hash,
            timing="evolution",
        ),
    )


def _family_evolution_split(base_task: TaskManifest) -> EvolutionSplitManifest:
    train_tasks = [
        base_task.model_copy(update={"task_id": f"family-{index}"})
        for index in (1, 2)
    ]
    validation_task = base_task.model_copy(update={"task_id": "family-3"})
    return EvolutionSplitManifest(
        benchmark="skilllearnbench",
        domain="skill_learning",
        seed=1,
        source_hash="c" * 64,
        train=[_evolution_pair(item) for item in train_tasks],
        validation=[_evolution_pair(validation_task)],
        clean_test=[],
    )


def _docker_task(tmp_path: Path) -> tuple[TaskManifest, Path]:
    instance = tmp_path / "docker-family-1"
    environment = instance / "environment"
    environment.mkdir(parents=True)
    (environment / "Dockerfile").write_text(
        "FROM python:3.11-slim\nWORKDIR /workspace\n",
        encoding="utf-8",
    )
    dependency = environment / "requirements.txt"
    dependency.write_text("pandas==2.2.0\n", encoding="utf-8")
    return (
        TaskManifest(
            task_id="docker-family-1",
            benchmark="skilllearnbench",
            domain="skill_learning",
            prompt="Create the requested artifact.",
            source_hash="d" * 64,
            artifact_path=str(instance),
            verifier="official:/tests/test.sh",
            metadata={"task_family": "docker-family"},
        ),
        dependency,
    )


def test_skilllearn_image_identity_is_content_addressed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    docker_task, dependency = _docker_task(tmp_path)
    images: dict[str, str] = {}
    build_commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        if command[1:3] == ["image", "inspect"]:
            tag = command[-1]
            if tag in images:
                return SimpleNamespace(returncode=0, stdout=images[tag] + "\n", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        if command[1] == "build":
            build_commands.append(command)
            tag = command[command.index("-t") + 1]
            images[tag] = f"sha256:{len(images) + 1:064x}"
            return SimpleNamespace(returncode=0, stdout="built", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(skilllearn_module.subprocess, "run", fake_run)
    backend = DockerSkillLearnBackend(client=object())

    first = backend.prepare(docker_task, tmp_path / "first")
    second = backend.prepare(docker_task, tmp_path / "second")

    assert first.context_hash == second.context_hash
    assert first.image_tag == second.image_tag
    assert first.image_id == second.image_id
    assert len(build_commands) == 1

    original_mtime = dependency.stat().st_mtime_ns
    dependency.write_text("pandas==2.2.1\n", encoding="utf-8")
    os.utime(dependency, ns=(original_mtime, original_mtime))
    changed = backend.prepare(docker_task, tmp_path / "changed")

    assert changed.context_hash != first.context_hash
    assert changed.image_tag != first.image_tag
    assert len(build_commands) == 2


def test_skilllearn_required_prebuilt_image_never_builds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    docker_task, _ = _docker_task(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout="", stderr="missing")

    monkeypatch.setattr(skilllearn_module.subprocess, "run", fake_run)
    backend = DockerSkillLearnBackend(client=object(), require_prebuilt=True)

    with pytest.raises(RuntimeError, match="prebuilt SkillLearn image is missing"):
        backend.prepare(docker_task, tmp_path / "formal")

    assert all(command[1] != "build" for command in commands)


def test_offline_verifier_installs_pinned_wheels_after_agent_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "pytest-8.4.1-py3-none-any.whl").write_bytes(b"wheel")
    output_dir = tmp_path / "execution"
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if "pytest" in command:
            return SimpleNamespace(returncode=1, stdout="failed", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(skilllearn_module.subprocess, "run", fake_run)
    backend = DockerSkillLearnBackend(
        client=object(),
        verifier_wheelhouse=wheelhouse,
    )

    verifier, diagnostics = backend._run_verifier("task-container", output_dir)

    assert verifier.returncode == 1
    assert diagnostics == {
        "verifier_mode": "offline_pytest",
        "verifier_bootstrap_returncode": 0,
    }
    assert (output_dir / "verifier/reward.txt").read_text() == "0\n"
    assert [
        "docker",
        "cp",
        f"{wheelhouse.resolve()}/.",
        "task-container:/tmp/rsebench-verifier-wheels",
    ] in commands
    install = next(command for command in commands if "pip" in command)
    assert "PIP_NO_INDEX=1" in install
    assert "PIP_BREAK_SYSTEM_PACKAGES=1" in install
    assert "pytest==8.4.1" in install
    assert "pytest-json-ctrf==0.3.5" in install
    pytest_command = next(command for command in commands if "pytest" in command)
    assert pytest_command[-8:] == [
        "python3",
        "-m",
        "pytest",
        "--ctrf",
        "/logs/verifier/ctrf.json",
        "/tests/test_outputs.py",
        "-rA",
        "-v",
    ]


def test_legacy_verifier_still_executes_official_script(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="passed", stderr="")

    monkeypatch.setattr(skilllearn_module.subprocess, "run", fake_run)
    backend = DockerSkillLearnBackend(client=object())

    verifier, diagnostics = backend._run_verifier("task-container", tmp_path)

    assert verifier.returncode == 0
    assert diagnostics == {"verifier_mode": "official_script"}
    assert commands == [
        ["docker", "exec", "task-container", "bash", "/tests/test.sh"]
    ]


def test_docker_volume_spec_resolves_relative_host_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    spec = _docker_volume_spec(Path("relative/run"), "/logs")

    assert spec == f"{(tmp_path / 'relative/run').resolve()}:/logs"


def test_skilllearn_container_is_registered_to_scheduler_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("RSEBENCH_ATTEMPT_ID", "attempt-123")
    monkeypatch.setenv("RSEBENCH_CONTAINER_PREFIX", "rsebench-attempt-123")

    name, registration = _container_runtime_identity(
        "offer-letter-generator-1",
        tmp_path / "execution",
    )

    assert name.startswith("rsebench-attempt-123-")
    assert registration == [
        "--label",
        "rsebench.attempt_id=attempt-123",
    ]


def test_container_tool_output_uses_replacement_decoding() -> None:
    source = Path(
        __import__("rsebench.evolution.skilllearn_executor", fromlist=["__file__"]).__file__
    ).read_text(encoding="utf-8")

    assert 'encoding="utf-8"' in source
    assert 'errors="replace"' in source


def test_command_tags_do_not_treat_read_only_python_as_artifact_write() -> None:
    inspection = "python3 - <<'PY'\nimport openpyxl\nprint(wb.sheetnames)\nPY"
    save = "python3 - <<'PY'\nwb.save('/root/gdp.xlsx')\nPY"

    assert "artifact_write" not in _command_tags(inspection)
    assert "artifact_write" in _command_tags(save)


def test_malformed_tool_arguments_get_a_bounded_retry_prompt() -> None:
    prompt = _tool_argument_recovery_prompt(
        RuntimeError("DeepSeek tool call 'run_shell' returned invalid JSON arguments")
    )

    assert prompt is not None
    assert "short single-line command" in prompt
    assert _tool_argument_recovery_prompt(RuntimeError("provider unavailable")) is None


def test_n3_trace_is_mutated_before_self_reflection_and_hidden_text_is_absent(tmp_path: Path) -> None:
    client = ScriptedClient(["diagnose visible trace", "revised skill"])
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="skilllearn_n3_omit_artifact_event",
        benchmark="skilllearnbench",
        domain="skill_learning",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["filesystem_change", "artifact_write"]},
    )
    executor = SkillLearnExecutor(
        client=client,
        backend=FakeBackend(),
        evidence_spec=spec,
        feedback_mode="self",
        ledger_dir=tmp_path / "tokens",
        run_id="run-1",
    )

    final_skill = executor.run_evolution_round(
        task=task(tmp_path),
        skill="seed skill",
        arm="noisy",
        output_dir=tmp_path / "round",
    )

    reflection_prompt = str(client.calls[0]["messages"])
    assert "write output.txt" not in reflection_prompt
    assert "inspect output.txt" in reflection_prompt
    assert FakeBackend.hidden not in reflection_prompt
    assert final_skill == "revised skill"
    assert (tmp_path / "round/mutation_audit/noisy/family-1/N3/audit.json").exists()
    assert [call["stage"] for call in client.calls] == [
        "skilllearn_self_feedback",
        "skilllearn_skill_rewrite",
    ]
    assert all(call["arm"] == "noisy" for call in client.calls)


def test_n4_changes_teacher_diagnosis_before_rewrite(tmp_path: Path) -> None:
    client = ScriptedClient(["Teacher blames the output write step.", "revised with wrong diagnosis"])
    spec = RuntimeNoiseSpec(
        stage="N4",
        operator="skilllearn_n4_replace_revision_diagnosis",
        benchmark="skilllearnbench",
        domain="skill_learning",
        seed=7,
        selector="same_kind_decoy_event",
        selector_parameters={
            "replacement_diagnosis": "The input inspection step caused the failure."
        },
    )
    executor = SkillLearnExecutor(
        client=client,
        backend=FakeBackend(),
        evidence_spec=spec,
        feedback_mode="teacher",
        ledger_dir=tmp_path / "tokens",
        run_id="run-2",
    )

    executor.run_evolution_round(
        task=task(tmp_path),
        skill="seed skill",
        arm="noisy",
        output_dir=tmp_path / "round",
    )

    teacher_prompt = str(client.calls[0]["messages"])
    rewrite_prompt = str(client.calls[1]["messages"])
    assert "wrong layout" in teacher_prompt
    assert FakeBackend.hidden not in teacher_prompt
    assert "input inspection step" in rewrite_prompt
    assert "Teacher blames the output write step" not in rewrite_prompt
    assert (tmp_path / "round/mutation_audit/noisy/family-1/N4/audit.json").exists()


def test_clean_arm_uses_identity_evidence_and_clean_sibling_evaluation(tmp_path: Path) -> None:
    client = ScriptedClient(["self diagnosis", "revised skill"])
    backend = FakeBackend()
    executor = SkillLearnExecutor(
        client=client,
        backend=backend,
        evidence_spec=None,
        feedback_mode="self",
        ledger_dir=tmp_path / "tokens",
        run_id="run-3",
    )
    acquisition = task(tmp_path)
    sibling = acquisition.model_copy(
        update={"task_id": "family-2", "source_hash": "b" * 64}
    )

    final_skill = executor.run_evolution_round(
        task=acquisition,
        skill="seed skill",
        arm="clean",
        output_dir=tmp_path / "round",
    )
    score = executor.evaluate_task(
        task=sibling,
        skill=final_skill,
        output_dir=tmp_path / "eval",
        arm="clean",
    )

    assert score == 1.0
    assert not (tmp_path / "round/mutation_audit").exists()


def test_production_evaluate_propagates_replay_stage_to_usage_context(
    tmp_path: Path,
) -> None:
    class StageBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.stages: list[str | None] = []

        def evaluate(self, task: TaskManifest, skill: str, output_dir: Path) -> float:
            self.stages.append(os.environ.get("RSEBENCH_TOKEN_STAGE"))
            return 1.0

    backend = StageBackend()
    executor = SkillLearnExecutor(
        client=ScriptedClient([]),
        backend=backend,
        evidence_spec=None,
        ledger_dir=tmp_path / "tokens",
        run_id="replay-stage",
    )
    skill = tmp_path / "skill.md"
    skill.write_text("skill\n", encoding="utf-8")

    result = executor.evaluate(
        skill_path=skill,
        clean_test=[task(tmp_path)],
        output_dir=tmp_path / "replay",
        stage="qualification_test_clean_artifact_repeat_1",
    )

    assert result.score == 1.0
    assert backend.stages == ["qualification_test_clean_artifact_repeat_1"]


def test_evolve_uses_family_validation_to_accept_revised_skills(tmp_path: Path) -> None:
    client = ScriptedClient(
        ["diagnosis one", "revised skill one", "diagnosis two", "revised skill two"]
    )
    backend = FakeBackend()
    executor = SkillLearnExecutor(
        client=client,
        backend=backend,
        evidence_spec=None,
        feedback_mode="self",
        ledger_dir=tmp_path / "tokens",
        run_id="run-validation",
    )
    base_task = task(tmp_path)
    split = _family_evolution_split(base_task)
    seed = tmp_path / "seed.md"
    seed.write_text("seed skill", encoding="utf-8")
    clean_arm, _ = build_arm_manifests(
        split,
        method="skilllearn_self_feedback",
        method_seed=1,
        seed_skill_hash=sha256_file(seed),
    )

    artifact = executor.evolve(
        arm=clean_arm,
        split=split,
        seed_skill_path=seed,
        output_dir=tmp_path / "evolve",
    )

    assert Path(artifact.skill_path).read_text(encoding="utf-8") == "revised skill two\n"
    assert [row["accepted"] for row in artifact.diagnostics["validation"]] == [
        True,
        True,
    ]
    assert artifact.diagnostics["validation_seed_score"] == 0.0
    assert (tmp_path / "evolve/evolution/round-1-family-1/acceptance.json").is_file()
    assert artifact.execution_audit is not None
    assert artifact.execution_audit.train_task_ids == ["family-1", "family-2"]
    assert artifact.execution_audit.validation_task_ids == ["family-3"]
    assert artifact.execution_audit.accepted_update_count == 2
    assert artifact.execution_audit.metadata["round_count"] == 2
    assert artifact.execution_audit.metadata["validation_evaluation_count"] == 3


def test_skilllearn_execution_audit_counts_only_accepted_candidates(
    tmp_path: Path,
) -> None:
    class RejectSecondBackend(FakeBackend):
        def evaluate(
            self,
            task: TaskManifest,
            skill: str,
            output_dir: Path,
        ) -> float:
            self.skills.append(skill)
            if "one" in skill:
                return 1.0
            return 0.0

    executor = SkillLearnExecutor(
        client=ScriptedClient(
            ["diagnosis one", "revised skill one", "diagnosis two", "revised skill two"]
        ),
        backend=RejectSecondBackend(),
        evidence_spec=None,
        feedback_mode="self",
        ledger_dir=tmp_path / "tokens",
        run_id="run-rejection",
    )
    split = _family_evolution_split(task(tmp_path))
    seed = tmp_path / "seed.md"
    seed.write_text("seed skill", encoding="utf-8")
    clean_arm, _ = build_arm_manifests(
        split,
        method="skilllearn_self_feedback",
        method_seed=1,
        seed_skill_hash=sha256_file(seed),
    )

    artifact = executor.evolve(
        arm=clean_arm,
        split=split,
        seed_skill_path=seed,
        output_dir=tmp_path / "evolve",
    )

    assert [row["accepted"] for row in artifact.diagnostics["validation"]] == [
        True,
        False,
    ]
    assert artifact.execution_audit is not None
    assert artifact.execution_audit.accepted_update_count == 1
    assert artifact.execution_audit.train_task_ids == ["family-1", "family-2"]
