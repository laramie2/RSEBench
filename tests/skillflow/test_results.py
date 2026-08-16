from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsebench.skillflow.contracts import SkillFlowFamilyManifest, SkillFlowTaskIdentity
from rsebench.skillflow.results import parse_arm_result, pair_replicate
from rsebench.usage.ledger import record_token_event


HASH_A = "a" * 64
HASH_B = "b" * 64


def _family() -> SkillFlowFamilyManifest:
    return SkillFlowFamilyManifest(
        family="Example-Family",
        status="ready",
        ranking_hash="c" * 64,
        ranked_task_ids=["task-1", "task-2"],
        tasks=[
            SkillFlowTaskIdentity(
                task_id="task-1",
                order=1,
                relative_path="Example-Family/task-1",
                task_hash=HASH_A,
            ),
            SkillFlowTaskIdentity(
                task_id="task-2",
                order=2,
                relative_path="Example-Family/task-2",
                task_hash=HASH_B,
            ),
        ],
        invalid_reasons=[],
    )


def _write_trial(
    job_dir: Path,
    task_id: str,
    reward: object,
    *,
    checksum: str,
    with_verifier: bool = True,
    exception_info: dict[str, object] | None = None,
    skill_use: bool = False,
) -> None:
    trial_dir = job_dir / f"trial-{task_id}"
    (trial_dir / "agent").mkdir(parents=True, exist_ok=True)
    verifier_result = {"rewards": {"reward": reward}} if with_verifier else None
    payload = {
        "task_name": task_id,
        "task_checksum": checksum,
        "verifier_result": verifier_result,
        "exception_info": exception_info,
        "started_at": "2026-08-16T10:00:00Z",
        "finished_at": "2026-08-16T10:00:10Z",
        "agent_execution": {
            "started_at": "2026-08-16T10:00:01Z",
            "finished_at": "2026-08-16T10:00:05Z",
        },
        "verifier": {
            "started_at": "2026-08-16T10:00:06Z",
            "finished_at": "2026-08-16T10:00:07Z",
        },
    }
    (trial_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    trajectory = {
        "steps": [
            {
                "tool_calls": (
                    [
                        {
                            "function_name": "Skill",
                            "arguments": {"skill": "shared-checklist"},
                        }
                    ]
                    if skill_use
                    else []
                )
            }
        ]
    }
    (trial_dir / "agent" / "trajectory.json").write_text(
        json.dumps(trajectory), encoding="utf-8"
    )


def _write_job(
    job_dir: Path,
    *,
    rewards: tuple[object, object] = (0.0, 1.0),
    include_patch_history: bool = True,
) -> None:
    job_dir.mkdir(parents=True)
    (job_dir / "result.json").write_text(
        json.dumps({"n_total_trials": 2}), encoding="utf-8"
    )
    _write_trial(job_dir, "task-1", rewards[0], checksum=HASH_A)
    _write_trial(job_dir, "task-2", rewards[1], checksum=HASH_B, skill_use=True)
    if include_patch_history:
        rows = [
            {
                "task_name": task_id,
                "upsert_paths": [f"{task_id}/SKILL.md"],
                "delete_paths": [],
                "started_at": "2026-08-16T10:00:07Z",
                "ended_at": "2026-08-16T10:00:09Z",
                "status": "applied",
            }
            for task_id in ("task-1", "task-2")
        ]
        (job_dir / "skill_patch_history.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    for index in range(2):
        record_token_event(
            usage={"prompt_tokens": 10, "completion_tokens": 2},
            cache_hit=False,
            billed=True,
            status="success",
            source="skillflow-test",
            provider="deepseek",
            model="deepseek-v4-flash",
            ledger_dir=job_dir / "token_usage",
            run_id="example-r1",
            domain="skill",
            benchmark="skillflow_tasks",
            arm="clean_evolution",
            stage=f"task-{index + 1}",
        )


def test_parse_complete_evolution_arm(tmp_path: Path) -> None:
    job_dir = tmp_path / "job"
    _write_job(job_dir)

    arm = parse_arm_result(
        job_dir,
        _family(),
        arm="clean_evolution",
        replicate_id="r1",
        expected_task_checksums={"task-1": HASH_A, "task-2": HASH_B},
    )

    assert arm.complete is True
    assert arm.task_rewards == [0.0, 1.0]
    assert arm.patch_count == 2
    assert arm.nonempty_patch_count == 2
    assert arm.skill_used_task_count == 1
    assert arm.task_results[1].agent_duration_seconds == 4.0
    assert arm.task_results[1].verifier_duration_seconds == 1.0
    assert arm.task_results[1].patch_duration_seconds == 2.0
    assert arm.token_usage.attempted_calls == 2
    assert arm.token_usage.observed_coverage == 1.0


def test_parse_native_harbor_trial_patch_ids_and_run_command_skill_reads(
    tmp_path: Path,
) -> None:
    """Native Harbor suffixes trial names and passes shell commands as argv."""

    job_dir = tmp_path / "job"
    _write_job(job_dir)
    native_trial_names = {
        "task-1": "task-1-truncated__AbC1234",
        "task-2": "task-2-truncated__DeF5678",
    }
    for task_id, trial_name in native_trial_names.items():
        (job_dir / f"trial-{task_id}").rename(job_dir / trial_name)
    rows = [
        {
            "trial_name": native_trial_names[task_id],
            "task_name": native_trial_names[task_id],
            "upsert_paths": [f"{task_id}/SKILL.md"],
            "delete_paths": [],
            "started_at": "2026-08-16T10:00:07Z",
            "ended_at": "2026-08-16T10:00:09Z",
            "status": "applied",
        }
        for task_id in ("task-1", "task-2")
    ]
    (job_dir / "skill_patch_history.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    trajectory_path = job_dir / native_trial_names["task-2"] / "agent" / "trajectory.json"
    trajectory_path.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "tool_calls": [
                            {
                                "function_name": "run_command",
                                "arguments": {
                                    "argv": [
                                        "cat",
                                        "/root/.agents/skills/shared-checklist/SKILL.md",
                                    ]
                                },
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    arm = parse_arm_result(
        job_dir,
        _family(),
        arm="clean_evolution",
        replicate_id="r1",
        expected_task_checksums={"task-1": HASH_A, "task-2": HASH_B},
    )

    assert arm.complete is True
    assert arm.patch_count == 2
    assert arm.nonempty_patch_count == 2
    assert arm.skill_used_task_count == 1
    assert arm.task_results[1].skills_used == ["shared-checklist"]


@pytest.mark.parametrize(
    ("mutation", "reason_prefix"),
    [
        ("missing_task", "missing_task:task-2"),
        ("duplicate_task", "duplicate_task:task-1"),
        ("exception", "execution_exception:task-2"),
        ("bad_reward", "invalid_reward:task-2"),
        ("checksum", "task_checksum_mismatch:task-2"),
        ("patch_history", "missing_patch_history"),
        ("patch_failure", "patch_execution_invalid:task-2:RuntimeError"),
        ("token_coverage", "invalid_token_coverage"),
    ],
)
def test_parse_invalid_evidence_is_typed(
    tmp_path: Path, mutation: str, reason_prefix: str
) -> None:
    job_dir = tmp_path / "job"
    _write_job(job_dir, include_patch_history=mutation != "patch_history")
    if mutation == "missing_task":
        trial = job_dir / "trial-task-2"
        for path in sorted(trial.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        trial.rmdir()
    elif mutation == "duplicate_task":
        duplicate = job_dir / "duplicate"
        duplicate.mkdir()
        source = json.loads((job_dir / "trial-task-1" / "result.json").read_text())
        (duplicate / "result.json").write_text(json.dumps(source), encoding="utf-8")
    elif mutation == "exception":
        _write_trial(
            job_dir,
            "task-2",
            0.0,
            checksum=HASH_B,
            with_verifier=False,
            exception_info={"exception_type": "AgentTimeoutError"},
        )
    elif mutation == "bad_reward":
        _write_trial(job_dir, "task-2", "not-a-number", checksum=HASH_B)
    elif mutation == "checksum":
        payload_path = job_dir / "trial-task-2" / "result.json"
        payload = json.loads(payload_path.read_text())
        payload["task_checksum"] = "different"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "patch_failure":
        history_path = job_dir / "skill_patch_history.jsonl"
        rows = [json.loads(line) for line in history_path.read_text().splitlines()]
        rows[1]["status"] = "failed"
        rows[1]["error_type"] = "RuntimeError"
        history_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    elif mutation == "token_coverage":
        record_token_event(
            usage=None,
            cache_hit=False,
            billed=False,
            status="error",
            source="skillflow-test",
            provider="deepseek",
            model="deepseek-v4-flash",
            ledger_dir=job_dir / "token_usage",
            run_id="example-r1",
            domain="skill",
            benchmark="skillflow_tasks",
            arm="clean_evolution",
            stage="patch",
            error_type="ProviderError",
        )

    arm = parse_arm_result(
        job_dir,
        _family(),
        arm="clean_evolution",
        replicate_id="r1",
        expected_task_checksums={"task-1": HASH_A, "task-2": HASH_B},
    )

    assert arm.complete is False
    assert any(reason.startswith(reason_prefix) for reason in arm.invalid_reasons)


def test_valid_failed_task_and_zero_patch_are_preserved(tmp_path: Path) -> None:
    job_dir = tmp_path / "job"
    _write_job(job_dir)
    _write_trial(
        job_dir,
        "task-2",
        0.0,
        checksum=HASH_B,
        with_verifier=True,
        exception_info={"exception_type": "AgentTerminatedError"},
    )
    rows = [
        {"task_name": task_id, "upsert_paths": [], "delete_paths": [], "status": "no_change"}
        for task_id in ("task-1", "task-2")
    ]
    (job_dir / "skill_patch_history.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    arm = parse_arm_result(
        job_dir,
        _family(),
        arm="clean_evolution",
        replicate_id="r1",
        expected_task_checksums={"task-1": HASH_A, "task-2": HASH_B},
    )

    assert arm.complete is True
    assert arm.task_rewards == [0.0, 0.0]
    assert arm.nonempty_patch_count == 0
    assert arm.task_results[1].exception_type == "AgentTerminatedError"


def test_pair_replicate_computes_late_and_full_delta(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    evolution_dir = tmp_path / "evolution"
    _write_job(base_dir, rewards=(1.0, 0.0))
    _write_job(evolution_dir, rewards=(0.0, 1.0))
    base = parse_arm_result(
        base_dir,
        _family(),
        arm="base",
        replicate_id="r1",
        expected_task_checksums={"task-1": HASH_A, "task-2": HASH_B},
    )
    evolution = parse_arm_result(
        evolution_dir,
        _family(),
        arm="clean_evolution",
        replicate_id="r1",
        expected_task_checksums={"task-1": HASH_A, "task-2": HASH_B},
    )

    paired = pair_replicate(base, evolution)

    assert paired.complete is True
    assert paired.delta_late == 1.0
    assert paired.delta_full == 0.0


def test_pair_replicate_rejects_checksum_drift(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    evolution_dir = tmp_path / "evolution"
    _write_job(base_dir)
    _write_job(evolution_dir)
    base = parse_arm_result(
        base_dir,
        _family(),
        arm="base",
        replicate_id="r1",
        expected_task_checksums={"task-1": HASH_A, "task-2": HASH_B},
    )
    evolution = parse_arm_result(
        evolution_dir,
        _family(),
        arm="clean_evolution",
        replicate_id="r1",
        expected_task_checksums={"task-1": HASH_A, "task-2": HASH_B},
    )
    drifted_task = evolution.task_results[1].model_copy(
        update={"task_checksum": "drifted"}
    )
    drifted = evolution.model_copy(
        update={"task_results": [evolution.task_results[0], drifted_task]}
    )

    paired = pair_replicate(base, drifted)

    assert paired.complete is False
    assert paired.invalid_reasons == ["paired_task_checksum_mismatch"]
