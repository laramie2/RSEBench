from __future__ import annotations

import os
from pathlib import Path

from rsebench.contracts import TaskManifest
from rsebench.evidence import RuntimeNoiseSpec, TraceEvent
from rsebench.evolution.skilllearn_executor import (
    _command_tags,
    _docker_volume_spec,
    _tool_argument_recovery_prompt,
    SkillLearnExecution,
    SkillLearnExecutor,
)
from rsebench.providers.deepseek import ModelResponse


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


def test_docker_volume_spec_resolves_relative_host_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    spec = _docker_volume_spec(Path("relative/run"), "/logs")

    assert spec == f"{(tmp_path / 'relative/run').resolve()}:/logs"


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
