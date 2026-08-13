from __future__ import annotations

import sys
import json
from pathlib import Path

from rsebench.evidence import HookContext, RuntimeNoiseSpec
from rsebench.evolution.skilladaptor_executor import (
    SkillAdaptorEvidenceAdapter,
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
    _rsebench_after_localizer,
    _rsebench_after_rollout,
)


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
