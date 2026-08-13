from __future__ import annotations

import sys
import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path

from rsebench.evidence import HookContext, RuntimeNoiseSpec
from rsebench.evolution.skilladaptor_executor import (
    SkillAdaptorBudget,
    SkillAdaptorEvidenceAdapter,
    SkillAdaptorExecutor,
    canonicalize_skill_bank_artifact,
    mutate_skilladaptor_fault,
    mutate_skilladaptor_trajectory,
)


METHOD_ROOT = Path(
    "/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor/skill-adaptor"
)
if str(METHOD_ROOT) not in sys.path:
    sys.path.insert(0, str(METHOD_ROOT))

from core.types import FaultType, LocalizedFault, Step, Trajectory  # noqa: E402
from core.orchestrator import (  # noqa: E402
    SkillAdaptorOrchestrator,
    _rsebench_after_localizer,
    _rsebench_after_rollout,
)
from core.llm_factory import _RetryingChatCompletions  # noqa: E402
from core.skill_matcher import SemanticSkillMatcher  # noqa: E402
from core.types import Skill, ValidationResult  # noqa: E402
from core.task_context import load_task_context_for_inference  # noqa: E402
from rsebench.usage import aggregate_token_usage, token_context_scope
from adapters.webshop_adapter.env_wrapper import (  # noqa: E402
    WebShopEnvWrapper,
    apply_goal_context,
    apply_product_overlay,
)
from adapters.webshop_adapter.llm_policy import SkillAugmentedLLMPolicy  # noqa: E402
from rsebench.contracts import TaskManifest
from rsebench.evolution.contracts import ArmTaskRef, EvolutionArmManifest


def _trajectory() -> Trajectory:
    return Trajectory(
        task_id="goal_17",
        task_description="Buy a red size large cotton shirt under $40.",
        steps=[
            Step(
                index=0,
                observation="Search page",
                action="search[cotton shirt]",
                reward=0.0,
            ),
            Step(
                index=1,
                observation="Product page: colors red and blue; sizes large and small",
                action="click[red]",
                reward=0.0,
            ),
            Step(
                index=2,
                observation="Product page: red selected",
                action="click[buy now]",
                reward=0.2,
                done=True,
            ),
        ],
        success=False,
        total_reward=0.2,
        error_step=2,
        metadata={"goal_idx": 17},
    )


def _context(tmp_path: Path, *, arm: str = "noisy") -> HookContext:
    return HookContext(
        task_id="goal_17",
        benchmark="webshop",
        domain="interactive",
        method="skilladaptor",
        arm=arm,
        run_dir=tmp_path,
    )


def test_clean_trajectory_path_is_exact_native_identity(tmp_path: Path) -> None:
    trajectory = _trajectory()

    output = mutate_skilladaptor_trajectory(
        trajectory, spec=None, context=_context(tmp_path, arm="clean")
    )

    assert output is trajectory


def test_n3_omits_required_option_before_localizer_and_preserves_reward(tmp_path: Path) -> None:
    trajectory = _trajectory()
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="webshop_n3_omit_constraint_event",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["required_option", "query_refinement"]},
    )

    output = mutate_skilladaptor_trajectory(
        trajectory, spec=spec, context=_context(tmp_path)
    )

    assert [step.action for step in output.steps] == [
        "search[cotton shirt]",
        "click[buy now]",
    ]
    assert output.total_reward == trajectory.total_reward
    assert output.success == trajectory.success
    assert output.task_description == trajectory.task_description
    assert trajectory.steps[1].action == "click[red]"
    assert (tmp_path / "mutation_audit/noisy/goal_17/N3/audit.json").exists()


def test_n4_replaces_native_fault_step_with_consistent_action_and_observation(
    tmp_path: Path,
) -> None:
    trajectory = _trajectory()
    fault = LocalizedFault(
        task_id=trajectory.task_id,
        step_index=2,
        fault_type=FaultType.REASONING_WRONG,
        observation=trajectory.steps[2].observation,
        wrong_action=trajectory.steps[2].action,
        skills_at_fault=[],
        improvement_principle="Verify every required option before buying.",
        fault_chain=[3],
    )
    spec = RuntimeNoiseSpec(
        stage="N4",
        operator="webshop_n4_replace_fault_step",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="same_kind_decoy_event",
        selector_parameters={
            "replacement_diagnosis": "The selected earlier action is the first fault."
        },
    )

    output = mutate_skilladaptor_fault(
        fault, trajectory, spec=spec, context=_context(tmp_path)
    )

    assert output.step_index in {0, 1}
    selected_step = trajectory.steps[output.step_index]
    assert output.observation == selected_step.observation
    assert output.wrong_action == selected_step.action
    assert output.improvement_principle == "The selected earlier action is the first fault."
    assert output.fault_type == fault.fault_type
    assert trajectory.total_reward == 0.2
    assert fault.step_index == 2
    assert (tmp_path / "mutation_audit/noisy/goal_17/N4/audit.json").exists()


def test_adapter_normalizes_native_step_positions_for_fault_round_trip(
    tmp_path: Path,
) -> None:
    trajectory = _trajectory()
    adapter = SkillAdaptorEvidenceAdapter(trajectory=trajectory)
    fault = LocalizedFault(
        task_id=trajectory.task_id,
        step_index=1,
        fault_type=FaultType.SKILL_MISSING,
        observation=trajectory.steps[1].observation,
        wrong_action=trajectory.steps[1].action,
        improvement_principle="Select required variants.",
    )

    normalized = adapter.normalize_feedback(fault, _context(tmp_path))
    restored = adapter.denormalize_feedback(
        fault, normalized, _context(tmp_path)
    )

    assert normalized.blamed_event_ids == ["step-1"]
    assert restored.step_index == 1
    assert restored.observation == trajectory.steps[1].observation
    assert restored.wrong_action == trajectory.steps[1].action


def test_external_orchestrator_hooks_use_public_env_contract(
    tmp_path: Path, monkeypatch
) -> None:
    trajectory = _trajectory()
    spec_path = tmp_path / "n3.json"
    spec_path.write_text(
        json.dumps(
            {
                "stage": "N3",
                "operator": "webshop_n3_omit_constraint_event",
                "benchmark": "webshop",
                "domain": "interactive",
                "seed": 7,
                "selector": "tag_priority",
                "selector_parameters": {"tags": ["required_option"]},
                "budget": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RSEBENCH_EVIDENCE_SPEC", str(spec_path))
    monkeypatch.setenv("RSEBENCH_EVIDENCE_AUDIT_ROOT", str(tmp_path / "run"))
    monkeypatch.setenv("RSEBENCH_EVIDENCE_ARM", "noisy")

    output = _rsebench_after_rollout(trajectory)

    assert [step.action for step in output.steps] == [
        "search[cotton shirt]",
        "click[buy now]",
    ]
    fault = LocalizedFault(
        task_id=trajectory.task_id,
        step_index=2,
        fault_type=FaultType.REASONING_WRONG,
        observation=trajectory.steps[2].observation,
        wrong_action=trajectory.steps[2].action,
        improvement_principle="original",
    )
    # An N3 spec is a strict identity at the N4 boundary.
    assert _rsebench_after_localizer(fault, trajectory) is fault


def test_lexical_matching_fallback_needs_no_embedding_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("SkillAdaptor_LEXICAL_MATCHING", "1")
    matcher = SemanticSkillMatcher(
        api_key="", base_url="", similarity_threshold=0.2
    )
    skills = {
        "variant": Skill(
            id="variant",
            title="Verify product variants",
            description="Check color and size before purchase",
            body="Select every required color and size option before buy now.",
        ),
        "unrelated": Skill(
            id="unrelated",
            title="Recover git branch",
            description="Inspect reflog and create a backup branch",
            body="Use git reflog before recovery.",
        ),
    }

    matches = matcher.match_skills_to_task(
        skills, "select the required red color and large size before purchase", top_k=2
    )

    assert matches
    assert matches[0][0].id == "variant"
    assert all(match.id != "unrelated" for match, _ in matches)


def test_skilladaptor_orchestrator_chat_records_observed_usage(tmp_path: Path) -> None:
    class FakeCompletions:
        kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(
                    prompt_tokens=11, completion_tokens=5, total_tokens=16
                ),
            )

    wrapper = _RetryingChatCompletions(FakeCompletions(), max_retries=1)
    with token_context_scope(
        ledger_dir=tmp_path / "tokens",
        run_id="skilladaptor-smoke",
        domain="interactive",
        benchmark="webshop",
        arm="clean",
        stage="evolution",
    ):
        wrapper.create(model="deepseek-v4-flash", messages=[])

    summary = aggregate_token_usage(tmp_path / "tokens")
    assert summary["attempted_calls"] == 1
    assert summary["observed_calls"] == 1
    assert summary["billed_tokens"]["total_tokens"] == 16
    assert "skilladaptor.orchestrator" in summary["groups"]["source"]
    assert wrapper._inner.kwargs["extra_body"] == {  # noqa: SLF001
        "thinking": {"type": "disabled"}
    }


def test_webshop_static_overlay_changes_view_not_catalog_or_goal() -> None:
    products = [
        {"asin": "TARGET", "name": "valid"},
        {"asin": "ORDINARY", "name": "ordinary"},
    ]
    catalog = {
        product["asin"]: product
        for product in products + [{"asin": "NEAR", "name": "near match"}]
    }
    overlay = {
        "stage": "N2",
        "output_product_ids": ["NEAR", "TARGET", "ORDINARY"],
        "promoted_product_id": "NEAR",
        "valid_target_ids": ["TARGET"],
    }

    output = apply_product_overlay(products, catalog, overlay)

    assert [product["asin"] for product in output[:3]] == [
        "NEAR",
        "TARGET",
        "ORDINARY",
    ]
    assert [product["asin"] for product in products] == ["TARGET", "ORDINARY"]
    assert catalog["NEAR"]["name"] == "near match"

    clean = "Instruction: buy a red shirt under $40"
    noisy = apply_goal_context(
        clean,
        {
            "stage": "N1",
            "clean_goal": "buy a red shirt under $40",
            "noisy_goal": (
                "buy a red shirt under $40\n\n"
                "Prior shopping session note (unverified): inspect NEAR first."
            ),
        },
    )
    assert noisy.startswith(clean)
    assert "Prior shopping session note" in noisy
    assert clean == "Instruction: buy a red shirt under $40"


def test_skill_bank_artifact_hash_ignores_wall_clock_metadata(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    template = {
        "skills": {
            "check": {
                "id": "check",
                "body": "verify every constraint",
                "created_at": "{stamp}",
                "updated_at": "{stamp}",
            }
        },
        "history": [{"action": "add", "skill_id": "check", "timestamp": "{stamp}"}],
    }
    for path, stamp in ((left, "2026-01-01"), (right, "2026-08-13")):
        payload = json.loads(json.dumps(template).replace("{stamp}", stamp))
        path.write_text(json.dumps(payload), encoding="utf-8")

    left_hash = canonicalize_skill_bank_artifact(left)
    right_hash = canonicalize_skill_bank_artifact(right)

    assert left_hash == right_hash
    assert "created_at" not in left.read_text(encoding="utf-8")
    assert "timestamp" not in right.read_text(encoding="utf-8")


def test_webshop_policy_requests_bounded_deterministic_action_completion() -> None:
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="Thought: inspect options.\nAction: search[red shirt]"
                        )
                    )
                ],
                usage=None,
            )

    policy = SkillAugmentedLLMPolicy.__new__(SkillAugmentedLLMPolicy)
    policy.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    policy.config = {"model": "deepseek-v4-flash", "max_retries": 1}

    action = policy._call_llm(  # noqa: SLF001
        "respond with action",
        {"has_search_bar": True, "clickables": []},
    )

    assert action == "search[red shirt]"
    assert captured["max_tokens"] >= 512
    assert captured["temperature"] == 0


def test_webshop_episode_records_policy_format_failure_as_zero_reward() -> None:
    wrapper = WebShopEnvWrapper.__new__(WebShopEnvWrapper)
    wrapper.env = object()
    wrapper.reset = lambda goal_idx: ("instruction", {})
    wrapper.get_available_actions = lambda: {
        "has_search_bar": True,
        "clickables": [],
    }

    class BrokenPolicy:
        def forward(self, *args, **kwargs):
            raise RuntimeError("no Action field")

    episode = wrapper.run_episode(7, BrokenPolicy(), max_steps=2)

    assert episode["total_reward"] == 0.0
    assert episode["success"] is False
    assert episode["num_steps"] == 0
    assert episode["error_type"] == "RuntimeError"


def test_interactive_task_context_can_fall_back_to_trajectory_text(monkeypatch) -> None:
    monkeypatch.delenv("TASKS_PATH", raising=False)
    monkeypatch.delenv("BENCHMARK_TASKS_PATH", raising=False)

    assert load_task_context_for_inference("goal_1503") == ""


def test_rejection_feedback_tolerates_failed_validation_episode() -> None:
    result = ValidationResult(
        skill_id="skill-1",
        delta_success=0.0,
        delta_avg_score=0.0,
        regression_detected=False,
        sample_size=1,
        baseline_metrics={},
        revised_metrics={"task_results": {"goal_1503": None}},
    )

    feedback = SkillAdaptorOrchestrator._validation_feedback_for_rejection(
        object(), result, "goal_1503"
    )

    assert "task=goal_1503" in feedback
    assert "score=0.00" in feedback


def _webshop_task(goal_idx: int) -> TaskManifest:
    return TaskManifest(
        task_id=f"goal_{goal_idx}",
        benchmark="webshop",
        domain="interactive",
        prompt=f"buy product for goal {goal_idx}",
        source_hash=f"{goal_idx:064x}",
        verifier="official:webshop_reward",
        metadata={"goal_idx": goal_idx},
    )


def test_skilladaptor_executor_runs_native_pair_boundary_and_clean_eval(
    tmp_path: Path, monkeypatch
) -> None:
    method_root = tmp_path / "skilladaptor" / "skill-adaptor"
    method_root.mkdir(parents=True)
    (method_root / "run_skill_adaptor.py").write_text("", encoding="utf-8")
    webshop_root = tmp_path / "webshop"
    webshop_root.mkdir()
    commands: list[list[str]] = []
    command_envs: list[dict[str, str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        command_envs.append(kwargs["env"])
        if command[1].endswith("run_skill_adaptor.py"):
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "skill_bank_final.json").write_text(
                json.dumps({"skills": {}, "history": []}), encoding="utf-8"
            )
            (output / "SkillAdaptor_report.json").write_text(
                json.dumps({"iterations": 1, "final_skill_count": 0}),
                encoding="utf-8",
            )
        else:
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "score": 0.5,
                        "per_task_scores": {"goal_3": 1.0, "goal_4": 0.0},
                        "diagnostics": {"sample_size": 2},
                    }
                ),
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    executor = SkillAdaptorExecutor(
        method_root=method_root,
        webshop_root=webshop_root,
        project_root=Path(__file__).resolve().parents[2],
        environment={"DEEPSEEK_API_KEY": "must-not-be-written"},
        budget=SkillAdaptorBudget(max_iterations=1, max_episode_steps=3),
        command_runner=fake_run,
    )
    monkeypatch.chdir(tmp_path)
    run_dir = Path("paired-run")
    run_dir.mkdir()
    executor.configure_token_run(run_dir)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"skills": {}, "history": []}), encoding="utf-8")
    arm = EvolutionArmManifest(
        arm="noisy",
        benchmark="webshop",
        domain="interactive",
        method="skilladaptor",
        method_seed=11,
        split_seed=7,
        split_source_hash="2" * 64,
        seed_skill_hash="1" * 64,
        train=[
            ArmTaskRef(
                pair_id="goal-1-pair",
                task_id="goal_1",
                payload_hash="3" * 64,
                noise_id="webshop-n3-goal-1",
            )
        ],
        validation=[
            ArmTaskRef(
                pair_id="goal-2-pair",
                task_id="goal_2",
                payload_hash="4" * 64,
                noise_id="webshop-n3-goal-2",
            )
        ],
        clean_test=[
            ArmTaskRef(
                pair_id="clean-test-goal-3",
                task_id="goal_3",
                payload_hash="5" * 64,
            ),
            ArmTaskRef(
                pair_id="clean-test-goal-4",
                task_id="goal_4",
                payload_hash="6" * 64,
            ),
        ],
        parameters={"stage": "N3"},
    )
    split = SimpleNamespace(
        benchmark="webshop",
        train=[SimpleNamespace(clean=_webshop_task(1), noisy=_webshop_task(1))],
        validation=[SimpleNamespace(clean=_webshop_task(2), noisy=_webshop_task(2))],
        clean_test=[_webshop_task(3), _webshop_task(4)],
    )

    artifact = executor.evolve(
        arm=arm,
        split=split,
        seed_skill_path=seed,
        output_dir=run_dir / "noisy",
    )
    evaluation = executor.evaluate(
        skill_path=Path(artifact.skill_path),
        clean_test=split.clean_test,
        output_dir=run_dir / "noisy" / "clean_test_evaluation",
        stage="noisy",
    )

    assert Path(artifact.skill_path).is_file()
    assert evaluation.score == 0.5
    assert evaluation.per_task_scores == {"goal_3": 1.0, "goal_4": 0.0}
    assert "--provider" in commands[0] and "deepseek" in commands[0]
    assert "--max-episode-steps" in commands[0]
    assert "--skip-held-out-test" in commands[0]
    assert command_envs[0]["RSEBENCH_EVIDENCE_SPEC"].endswith(
        "benchmark/core1/runtime/webshop/N3.json"
    )
    assert command_envs[0]["RSEBENCH_EVIDENCE_ARM"] == "noisy"
    assert "RSEBENCH_EVIDENCE_SPEC" not in command_envs[1]
    assert command_envs[0]["RSEBENCH_TOKEN_STAGE"] == "evolution"
    assert command_envs[1]["RSEBENCH_TOKEN_STAGE"] == "eval"
    assert command_envs[0]["SkillAdaptor_MIN_SAMPLE_SIZE"] == "1"
    training_manifest = json.loads(
        (run_dir / "noisy" / "webshop_task_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    evaluation_manifest = json.loads(
        (
            run_dir
            / "noisy"
            / "clean_test_evaluation"
            / "webshop_task_manifest.json"
        ).read_text(encoding="utf-8")
    )
    # The paired harness owns the untouched clean test.  Passing it into the
    # native trainer would evaluate it redundantly before the frozen-bank eval.
    assert training_manifest["test_tasks"] == []
    assert evaluation_manifest["test_tasks"] == [3, 4]
    for command in commands:
        for flag in ("--task-manifest", "--manifest", "--skills", "--output"):
            if flag in command:
                assert Path(command[command.index(flag) + 1]).is_absolute()
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    assert "must-not-be-written" not in persisted


def test_skilladaptor_eval_script_imports_from_nonproject_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root / "src")

    completed = subprocess.run(
        [sys.executable, str(root / "scripts/eval_skilladaptor_webshop.py"), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
