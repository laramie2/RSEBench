from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rsebench.hashing import sha256_file, sha256_tree
from rsebench.evidence import canonical_hash
from rsebench.skillflow.contracts import (
    SkillFlowCleanConfig,
    SkillFlowFamilyManifest,
    SkillFlowInputManifest,
    SkillFlowQualificationGate,
    SkillFlowRuntimeConfig,
    SkillFlowTaskIdentity,
)
from rsebench.skillflow.runner import (
    aggregate_evidence,
    build_arm_command,
    build_native_config,
    freeze_qualified,
    plan_attempt,
    run_preflight,
    select_batch_b_families,
    select_confirmation_families,
    validate_provider_cost,
)
from rsebench.skillflow.results import (
    SkillFlowArmResult,
    SkillFlowReplicateResult,
    SkillFlowTaskResult,
    SkillFlowTokenUsage,
)


UPSTREAM = "7b49ff5a7e26cd7706e959bfa0dba4746d18440d"
IMAGE = "skillevlove/harbor-cli-openhands:ubuntu24.04"
NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _candidate(root: Path, family: str = "Family-A") -> SkillFlowFamilyManifest:
    family_dir = root / family
    family_dir.mkdir(parents=True)
    ranking = ["task-1", "task-2"]
    ranking_path = family_dir / "ALL_TASK_DIFFICULTY_RANKING.json"
    ranking_path.write_text(json.dumps(ranking), encoding="utf-8")
    tasks = []
    for order, task_id in enumerate(ranking, 1):
        task_dir = family_dir / task_id
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("version = '1.0'\n", encoding="utf-8")
        (task_dir / "instruction.md").write_text("Do the task.\n", encoding="utf-8")
        for directory in ("environment", "solution", "tests"):
            (task_dir / directory).mkdir()
        (task_dir / "environment" / "Dockerfile").write_text(
            f"FROM {IMAGE}\n", encoding="utf-8"
        )
        tasks.append(
            SkillFlowTaskIdentity(
                task_id=task_id,
                order=order,
                relative_path=f"{family}/{task_id}",
                task_hash=sha256_tree(task_dir),
            )
        )
    return SkillFlowFamilyManifest(
        family=family,
        status="ready",
        ranking_hash=sha256_file(ranking_path),
        ranked_task_ids=ranking,
        tasks=tasks,
        invalid_reasons=[],
    )


def _runtime() -> SkillFlowRuntimeConfig:
    return SkillFlowRuntimeConfig(
        model="deepseek-v4-flash",
        thinking="disabled",
        temperature=0.0,
        max_turns=60,
        max_completion_tokens=8192,
        patch_temperature=0.2,
        patch_max_tokens=8192,
        patch_max_steps=60,
        patch_max_observation_chars=3000,
        docker_image=IMAGE,
        arm_timeout_seconds=21600,
    )


def _gate() -> SkillFlowQualificationGate:
    return SkillFlowQualificationGate(
        minimum_positive_replicates=2,
        minimum_nonnegative_replicates=3,
        minimum_patch_replicates=3,
        minimum_skill_use_replicates=2,
        require_positive_pooled_full_delta=True,
        target_qualified_families=2,
    )


def _config(data_root: Path, output_root: Path) -> SkillFlowCleanConfig:
    return SkillFlowCleanConfig(
        schema_version="rsebench.skillflow-clean-config.v1",
        benchmark="skillflow_tasks",
        baseline="skillflow",
        upstream_revision=UPSTREAM,
        qualification_contract="skillflow-clean-qualification-v1",
        data_root=str(data_root),
        output_root=str(output_root),
        batch_a=["Family-A"],
        batch_b=[],
        replicates=["r1", "r2", "r3"],
        runtime=_runtime(),
        qualification=_gate(),
    )


def _manifest(data_root: Path, output_root: Path) -> SkillFlowInputManifest:
    config = _config(data_root, output_root)
    return SkillFlowInputManifest(
        schema_version="rsebench.skillflow-input.v1",
        benchmark="skillflow_tasks",
        baseline="skillflow",
        upstream_revision=UPSTREAM,
        qualification_contract="skillflow-clean-qualification-v1",
        config_hash=canonical_hash(config),
        runtime=config.runtime,
        qualification=config.qualification,
        batch_a=config.batch_a,
        batch_b=config.batch_b,
        replicates=config.replicates,
        families=[_candidate(data_root)],
        provider_calls=0,
    )


def _arm_result(
    family: str,
    replicate_id: str,
    arm: str,
    rewards: list[float],
    *,
    patch: bool = False,
    skill_use: bool = False,
) -> SkillFlowArmResult:
    tasks = [
        SkillFlowTaskResult(
            task_id=f"task-{index + 1}",
            order=index + 1,
            reward=reward,
            task_checksum=f"checksum-{index + 1}",
            started_at=NOW,
            finished_at=NOW,
            duration_seconds=0.0,
            agent_duration_seconds=0.0,
            verifier_duration_seconds=0.0,
            patch_duration_seconds=0.0 if patch else None,
            skill_use_calls=1 if skill_use and index == 1 else 0,
            skills_used=["shared"] if skill_use and index == 1 else [],
            exception_type=None,
        )
        for index, reward in enumerate(rewards)
    ]
    return SkillFlowArmResult(
        family=family,
        replicate_id=replicate_id,
        arm=arm,
        complete=True,
        invalid_reasons=[],
        task_results=tasks,
        task_rewards=rewards,
        patch_count=len(tasks) if patch else 0,
        nonempty_patch_count=len(tasks) if patch else 0,
        skill_used_task_count=1 if skill_use else 0,
        started_at=NOW,
        finished_at=NOW,
        duration_seconds=0.0,
        token_usage=SkillFlowTokenUsage(
            attempted_calls=2,
            observed_calls=2,
            observed_coverage=1.0,
            prompt_tokens=20,
            completion_tokens=4,
            total_tokens=24,
        ),
    )


def _paired(family: str, replicate_id: str, delta_late: float) -> SkillFlowReplicateResult:
    base = _arm_result(family, replicate_id, "base", [0.0, 0.0])
    evolution = _arm_result(
        family,
        replicate_id,
        "clean_evolution",
        [0.25, delta_late],
        patch=True,
        skill_use=True,
    )
    return SkillFlowReplicateResult(
        family=family,
        replicate_id=replicate_id,
        complete=True,
        invalid_reasons=[],
        base=base,
        evolution=evolution,
        delta_late=delta_late,
        delta_full=(0.25 + delta_late) / 2,
    )


def _two_family_manifest(data_root: Path, output_root: Path) -> SkillFlowInputManifest:
    family_a = _candidate(data_root, "Family-A")
    family_b = _candidate(data_root, "Family-B")
    config = _config(data_root, output_root).model_copy(
        update={"batch_a": ["Family-A", "Family-B"]}
    )
    return SkillFlowInputManifest(
        schema_version="rsebench.skillflow-input.v1",
        benchmark="skillflow_tasks",
        baseline="skillflow",
        upstream_revision=UPSTREAM,
        qualification_contract="skillflow-clean-qualification-v1",
        config_hash=canonical_hash(config),
        runtime=config.runtime,
        qualification=config.qualification,
        batch_a=["Family-A", "Family-B"],
        batch_b=[],
        replicates=["r1", "r2", "r3"],
        families=[family_a, family_b],
        provider_calls=0,
    )


def test_native_configs_are_serial_empty_skill_and_secret_free(tmp_path: Path) -> None:
    config = _config(tmp_path / "data", tmp_path / "out")
    family_path = tmp_path / "data" / "Family-A"

    base = build_native_config(
        config, family="Family-A", family_path=family_path, replicate_id="r1", arm="base"
    )
    evolution = build_native_config(
        config,
        family="Family-A",
        family_path=family_path,
        replicate_id="r1",
        arm="clean_evolution",
    )

    for payload in (base, evolution):
        assert payload["agents"][0]["import_path"].endswith(":DeepSeekAPIAgent")
        assert payload["agents"][0]["model_name"] == "deepseek-v4-flash"
        assert payload["agents"][0]["kwargs"]["max_turns"] == 60
        assert payload["agents"][0]["kwargs"]["max_tokens"] == 8192
        assert payload["environment"]["force_build"] is True
        assert payload["orchestrator"]["n_concurrent_trials"] == 1
        assert payload["datasets"] == [{"path": str(family_path)}]
        encoded = json.dumps(payload)
        assert "API_KEY" not in encoded
        assert "project_template_dir" not in encoded
        assert "copy_task_skills" not in encoded
    assert base["environment"].get("import_path") is None
    assert evolution["environment"].get("import_path") is None


def test_arm_commands_are_exact_and_do_not_copy_task_skills(tmp_path: Path) -> None:
    config = _config(tmp_path / "data", tmp_path / "out")
    method_root = tmp_path / "skillflow"
    yaml_path = tmp_path / "arm.yaml"
    family_path = tmp_path / "data" / "Family-A"
    arm_root = tmp_path / "arm"

    base = build_arm_command(
        python="python",
        method_root=method_root,
        config_path=yaml_path,
        family="Family-A",
        family_path=family_path,
        arm_root=arm_root,
        arm="base",
        runtime=config.runtime,
    )
    evolution = build_arm_command(
        python="python",
        method_root=method_root,
        config_path=yaml_path,
        family="Family-A",
        family_path=family_path,
        arm_root=arm_root,
        arm="clean_evolution",
        runtime=config.runtime,
    )

    assert base == [
        "python",
        str(method_root / "family_job_runner.py"),
        "--config",
        str(yaml_path),
        "--only-group",
        "Family-A",
        "--dataset-path",
        str(family_path),
        "--run-root-dir",
        str(arm_root),
    ]
    assert evolution == [
        "python",
        str(method_root / "iterative_shared_skills_runner.py"),
        "--config",
        str(yaml_path),
        "--only-group",
        "Family-A",
        "--dataset-path",
        str(family_path),
        "--run-root-dir",
        str(arm_root),
        "--max-steps",
        "60",
        "--max-obs-chars",
        "3000",
        "--patch-temperature",
        "0.2",
        "--patch-max-tokens",
        "8192",
    ]
    assert "--copy-task-skills" not in evolution


def test_preflight_is_offline_and_ready_with_verified_inputs(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    config = _config(data_root, output_root)
    manifest = _manifest(data_root, output_root)

    report = run_preflight(
        project_root=tmp_path,
        method_root=tmp_path / "skillflow",
        config=config,
        manifest=manifest,
        output_root=output_root,
        baseline_check=lambda: {"fingerprint": "f" * 64},
        image_inspector=lambda image: f"{image}@sha256:{'a' * 64}",
    )

    assert report.status == "ready"
    assert report.provider_calls == 0
    assert all(report.checks.values())
    assert report.docker_image_digest.endswith("a" * 64)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("baseline", "baseline_unverified"),
        ("image", "docker_image_unavailable"),
        ("hash", "input_manifest_invalid"),
        ("skills", "initial_skills_not_empty"),
        ("collision", "output_collision"),
    ],
)
def test_preflight_fails_closed_with_typed_reason(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    config = _config(data_root, output_root)
    manifest = _manifest(data_root, output_root)
    skills = tmp_path / "initial-skills"
    baseline_check = lambda: {"fingerprint": "f" * 64}
    image_inspector = lambda image: f"{image}@sha256:{'a' * 64}"
    if mutation == "baseline":
        baseline_check = lambda: (_ for _ in ()).throw(RuntimeError("dirty"))
    elif mutation == "image":
        image_inspector = lambda image: (_ for _ in ()).throw(RuntimeError("missing"))
    elif mutation == "hash":
        (data_root / "Family-A" / "task-1" / "instruction.md").write_text(
            "drifted\n", encoding="utf-8"
        )
    elif mutation == "skills":
        skills.mkdir()
        (skills / "SKILL.md").write_text("not empty", encoding="utf-8")
    elif mutation == "collision":
        output_root.mkdir()
        (output_root / "unexpected.txt").write_text("collision", encoding="utf-8")

    report = run_preflight(
        project_root=tmp_path,
        method_root=tmp_path / "skillflow",
        config=config,
        manifest=manifest,
        output_root=output_root,
        initial_skills_dir=skills,
        baseline_check=baseline_check,
        image_inspector=image_inspector,
    )

    assert report.status == "blocked"
    assert reason in report.reasons
    assert report.provider_calls == 0


def test_provider_cost_gate_and_dry_run_attempt(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="confirm-provider-cost"):
        validate_provider_cost(dry_run=False, confirm_provider_cost=False)
    validate_provider_cost(dry_run=True, confirm_provider_cost=False)

    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    config = _config(data_root, output_root)
    manifest = _manifest(data_root, output_root)
    attempt = plan_attempt(
        phase="screen",
        attempt_id="screen-dry-run",
        project_root=tmp_path,
        method_root=tmp_path / "skillflow",
        output_root=output_root,
        config=config,
        manifest=manifest,
        dry_run=True,
    )

    assert attempt.provider_calls == 0
    assert attempt.phase == "screen"
    assert len(attempt.arms) == 2
    persisted = json.loads(
        (output_root / "attempts" / "screen-dry-run" / "run_manifest.json").read_text()
    )
    assert persisted["provider_calls"] == 0
    assert persisted["dry_run"] is True
    assert all(Path(item["config_path"]).is_file() for item in persisted["arms"])


def test_attempt_defaults_to_the_skillflow_virtualenv_python(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    method_root = tmp_path / "skillflow"
    config = _config(data_root, output_root)
    manifest = _manifest(data_root, output_root)

    attempt = plan_attempt(
        phase="screen",
        attempt_id="method-python",
        project_root=tmp_path,
        method_root=method_root,
        output_root=output_root,
        config=config,
        manifest=manifest,
        dry_run=True,
    )

    assert {arm.command[0] for arm in attempt.arms} == {
        str(method_root / ".venv/bin/python")
    }


def test_attempt_collision_is_never_overwritten(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    config = _config(data_root, output_root)
    manifest = _manifest(data_root, output_root)
    kwargs = dict(
        phase="screen",
        attempt_id="same",
        project_root=tmp_path,
        method_root=tmp_path / "skillflow",
        output_root=output_root,
        config=config,
        manifest=manifest,
        dry_run=True,
    )
    plan_attempt(**kwargs)

    with pytest.raises(FileExistsError, match="attempt already exists"):
        plan_attempt(**kwargs)


def test_confirm_plan_schedules_only_missing_replicates(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    config = _config(data_root, output_root)
    manifest = _manifest(data_root, output_root)

    attempt = plan_attempt(
        phase="confirm",
        attempt_id="confirm-missing",
        project_root=tmp_path,
        method_root=tmp_path / "skillflow",
        output_root=output_root,
        config=config,
        manifest=manifest,
        dry_run=True,
        selected_families=["Family-A"],
        missing_replicates={"Family-A": ["r3"]},
    )

    assert {(arm.replicate_id, arm.arm) for arm in attempt.arms} == {
        ("r3", "base"),
        ("r3", "clean_evolution"),
    }


def test_aggregate_marks_screen_and_formal_qualification(tmp_path: Path) -> None:
    manifest = _two_family_manifest(tmp_path / "data", tmp_path / "output")
    aggregate = aggregate_evidence(
        manifest,
        {
            "Family-A": [_paired("Family-A", "r1", 0.5)],
            "Family-B": [
                _paired("Family-B", "r1", 0.5),
                _paired("Family-B", "r2", 0.25),
                _paired("Family-B", "r3", 0.0),
            ],
        },
    )

    by_family = {family.family: family for family in aggregate.families}
    assert by_family["Family-A"].status == "preliminary_positive"
    assert by_family["Family-B"].status == "qualified"
    assert aggregate.provider_calls == 16


def test_freeze_requires_two_qualified_families_and_writes_compact_evidence(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    manifest = _two_family_manifest(data_root, tmp_path / "output")
    only_one = aggregate_evidence(
        manifest,
        {
            "Family-A": [
                _paired("Family-A", "r1", 0.5),
                _paired("Family-A", "r2", 0.25),
                _paired("Family-A", "r3", 0.0),
            ]
        },
    )
    with pytest.raises(RuntimeError, match="1/2 families qualify"):
        freeze_qualified(
            aggregate=only_one,
            manifest=manifest,
            data_root=data_root,
            output_path=tmp_path / "frozen.json",
        )

    both = aggregate_evidence(
        manifest,
        {
            family: [
                _paired(family, "r1", 0.5),
                _paired(family, "r2", 0.25),
                _paired(family, "r3", 0.0),
            ]
            for family in ("Family-A", "Family-B")
        },
    )
    frozen_path = tmp_path / "frozen.json"
    frozen = freeze_qualified(
        aggregate=both,
        manifest=manifest,
        data_root=data_root,
        output_path=frozen_path,
    )

    assert frozen["qualified_families"] == ["Family-A", "Family-B"]
    encoded = frozen_path.read_text(encoding="utf-8")
    assert "trajectory" not in encoded.lower()
    assert "api_key" not in encoded.lower()


def test_adaptive_selection_requires_completed_batch_a_and_preliminary_signal(
    tmp_path: Path,
) -> None:
    manifest = _two_family_manifest(tmp_path / "data", tmp_path / "output")
    unscreened = aggregate_evidence(manifest, {})
    with pytest.raises(RuntimeError, match="Batch A screening is incomplete"):
        select_batch_b_families(unscreened, manifest)

    one_positive = aggregate_evidence(
        manifest,
        {
            "Family-A": [_paired("Family-A", "r1", 0.5)],
            "Family-B": [_paired("Family-B", "r1", 0.0)],
        },
    )
    assert select_batch_b_families(one_positive, manifest) == []
    assert select_confirmation_families(one_positive, manifest, None) == ["Family-A"]
    with pytest.raises(ValueError, match="not preliminary-positive"):
        select_confirmation_families(one_positive, manifest, ["Family-B"])
