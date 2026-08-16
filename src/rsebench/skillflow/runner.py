"""Offline-safe control plane for SkillFlow clean screening and freezing."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

import yaml
from pydantic import Field

from rsebench.evidence import canonical_hash
from rsebench.experiments.bootstrap import load_patch_series, verify_baseline
from rsebench.experiments.timing import TimingRecorder
from rsebench.skillflow.contracts import (
    FrozenStrictModel,
    SkillFlowCleanConfig,
    SkillFlowFamilyManifest,
    SkillFlowInputManifest,
    SkillFlowRuntimeConfig,
)
from rsebench.skillflow.manifest import verify_input_manifest
from rsebench.skillflow.qualification import (
    SkillFlowFamilyDecision,
    is_preliminary_positive,
    qualify_family,
)
from rsebench.skillflow.results import (
    ArmName,
    ReplicateId,
    SkillFlowReplicateResult,
    pair_replicate,
    parse_arm_result,
)
from rsebench.usage import token_context_environment


Phase = Literal["screen", "confirm"]
FamilyStatus = Literal[
    "input_invalid",
    "unscreened",
    "preliminary_positive",
    "screened_out",
    "incomplete",
    "qualified",
    "not_qualified",
]

_ALLOWED_OUTPUT_ENTRIES = {"aggregate.json", "attempts", "preflight.json"}


class SkillFlowPreflightReport(FrozenStrictModel):
    schema_version: Literal["rsebench.skillflow-preflight.v1"]
    status: Literal["ready", "blocked"]
    checked_at: datetime
    provider_calls: Literal[0] = 0
    checks: dict[str, bool]
    reasons: list[str]
    baseline_fingerprint: str | None
    docker_image: str
    docker_image_digest: str | None
    input_manifest_hash: str


class SkillFlowArmPlan(FrozenStrictModel):
    family: str = Field(min_length=1)
    replicate_id: ReplicateId
    arm: ArmName
    config_path: str = Field(min_length=1)
    arm_root: str = Field(min_length=1)
    job_dir: str = Field(min_length=1)
    command: list[str] = Field(min_length=1)


class SkillFlowRunManifest(FrozenStrictModel):
    schema_version: Literal["rsebench.skillflow-run.v1"]
    attempt_id: str = Field(min_length=1)
    phase: Phase
    created_at: datetime
    dry_run: bool
    provider_calls: int = Field(ge=0)
    project_root: str = Field(min_length=1)
    method_root: str = Field(min_length=1)
    output_root: str = Field(min_length=1)
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    families: list[str]
    input_invalid_families: dict[str, list[str]]
    arms: list[SkillFlowArmPlan]


class SkillFlowFamilyAggregate(FrozenStrictModel):
    family: str = Field(min_length=1)
    status: FamilyStatus
    reasons: list[str]
    preliminary_positive: bool
    replicates: list[SkillFlowReplicateResult]
    decision: SkillFlowFamilyDecision | None


class SkillFlowAggregate(FrozenStrictModel):
    schema_version: Literal["rsebench.skillflow-aggregate.v1"]
    created_at: datetime
    input_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_calls: int = Field(ge=0)
    families: list[SkillFlowFamilyAggregate]


class SkillFlowExecutionError(RuntimeError):
    """A native arm failed before complete parseable paired evidence existed."""


def _write_json(path: Path, payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = yaml.safe_dump(dict(payload), sort_keys=False, allow_unicode=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def validate_provider_cost(*, dry_run: bool, confirm_provider_cost: bool) -> None:
    if not dry_run and not confirm_provider_cost:
        raise RuntimeError(
            "provider-backed SkillFlow execution requires --confirm-provider-cost"
        )


def build_native_config(
    config: SkillFlowCleanConfig,
    *,
    family: str,
    family_path: Path | str,
    replicate_id: ReplicateId,
    arm: ArmName,
) -> dict[str, Any]:
    """Build a secret-free Harbor config; the native runner supplies shared skills."""

    family_root = Path(family_path).resolve()
    job_arm = "evolution" if arm == "clean_evolution" else "base"
    return {
        "job_name": f"skillflow-{job_arm}-{replicate_id}",
        "agents": [
            {
                "import_path": (
                    "libs.harbor_noinstall_agents.deepseek_api:DeepSeekAPIAgent"
                ),
                "model_name": config.runtime.model,
                "env": {},
                "kwargs": {
                    "role": "worker",
                    "max_turns": config.runtime.max_turns,
                    "base_url": "https://api.deepseek.com/v1",
                },
            }
        ],
        "environment": {
            "allow_internet": True,
            "force_build": True,
            "delete": False,
        },
        "orchestrator": {
            "type": "local",
            "n_concurrent_trials": 1,
            "quiet": False,
        },
        "datasets": [{"path": str(family_root)}],
    }


def build_arm_command(
    *,
    python: str,
    method_root: Path | str,
    config_path: Path | str,
    family: str,
    family_path: Path | str,
    arm_root: Path | str,
    arm: ArmName,
    runtime: SkillFlowRuntimeConfig,
) -> list[str]:
    method = Path(method_root).resolve()
    script = (
        method / "family_job_runner.py"
        if arm == "base"
        else method / "iterative_shared_skills_runner.py"
    )
    command = [
        python,
        str(script),
        "--config",
        str(Path(config_path).resolve()),
        "--only-group",
        family,
        "--dataset-path",
        str(Path(family_path).resolve()),
        "--run-root-dir",
        str(Path(arm_root).resolve()),
    ]
    if arm == "clean_evolution":
        command.extend(
            [
                "--max-steps",
                str(runtime.patch_max_steps),
                "--max-obs-chars",
                str(runtime.patch_max_observation_chars),
                "--patch-temperature",
                str(runtime.patch_temperature),
                "--patch-max-tokens",
                str(runtime.patch_max_tokens),
            ]
        )
    return command


def _default_image_inspector(image: str) -> str:
    completed = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail or f"Docker image unavailable: {image}")
    digest = completed.stdout.strip()
    if not digest:
        raise RuntimeError(f"Docker image has no digest: {image}")
    return digest


def _default_baseline_check(
    project_root: Path, method_root: Path, revision: str
) -> dict[str, Any]:
    registry_path = project_root / "benchmark/registry/methods.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    specification = registry["methods"]["skillflow"]
    series_path = (project_root / specification["patch_series"]).resolve()
    series = load_patch_series(series_path)
    fingerprint = verify_baseline(
        method_root,
        series,
        series_path=series_path,
        repository=str(specification["repository"]),
        revision=revision,
    )
    return fingerprint.model_dump(mode="json")


def _dockerfile_base_images(
    data_root: Path, families: Sequence[SkillFlowFamilyManifest]
) -> set[str]:
    images: set[str] = set()
    for family in families:
        if family.status != "ready":
            continue
        for task in family.tasks:
            dockerfile = data_root / task.relative_path / "environment" / "Dockerfile"
            if not dockerfile.is_file():
                continue
            for line in dockerfile.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.upper().startswith("FROM "):
                    images.add(stripped.split()[1])
                    break
    return images


def run_preflight(
    *,
    project_root: Path | str,
    method_root: Path | str,
    config: SkillFlowCleanConfig,
    manifest: SkillFlowInputManifest,
    output_root: Path | str,
    initial_skills_dir: Path | str | None = None,
    baseline_check: Callable[[], Mapping[str, Any]] | None = None,
    image_inspector: Callable[[str], str] | None = None,
) -> SkillFlowPreflightReport:
    """Run source/data/image/output checks without loading credentials or providers."""

    project = Path(project_root).resolve()
    method = Path(method_root).resolve()
    output = Path(output_root).resolve()
    data_root = Path(config.data_root)
    if not data_root.is_absolute():
        data_root = (project / data_root).resolve()
    reasons: list[str] = []
    checks = {
        "config_identity": False,
        "baseline_verified": False,
        "input_manifest_verified": False,
        "docker_image_verified": False,
        "initial_skills_empty": False,
        "output_isolated": False,
    }

    if canonical_hash(config) == manifest.config_hash and (
        config.runtime == manifest.runtime
        and config.qualification == manifest.qualification
        and config.batch_a == manifest.batch_a
        and config.batch_b == manifest.batch_b
    ):
        checks["config_identity"] = True
    else:
        reasons.append("config_manifest_mismatch")

    baseline_payload: Mapping[str, Any] | None = None
    try:
        check = baseline_check or (
            lambda: _default_baseline_check(project, method, config.upstream_revision)
        )
        baseline_payload = check()
        fingerprint = baseline_payload.get("fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("baseline fingerprint missing")
        checks["baseline_verified"] = True
    except Exception:
        reasons.append("baseline_unverified")

    try:
        verify_input_manifest(manifest, data_root=data_root)
        checks["input_manifest_verified"] = True
    except Exception:
        reasons.append("input_manifest_invalid")

    image_digest: str | None = None
    try:
        referenced = _dockerfile_base_images(data_root, manifest.families)
        if referenced != {config.runtime.docker_image}:
            raise RuntimeError(
                f"task Dockerfiles reference {sorted(referenced)}, not "
                f"{config.runtime.docker_image}"
            )
        inspector = image_inspector or _default_image_inspector
        image_digest = inspector(config.runtime.docker_image)
        if not image_digest:
            raise RuntimeError("empty image digest")
        checks["docker_image_verified"] = True
    except Exception:
        reasons.append("docker_image_unavailable")

    skills = Path(initial_skills_dir).resolve() if initial_skills_dir else None
    if skills is None or not skills.exists() or not any(path.is_file() for path in skills.rglob("*")):
        checks["initial_skills_empty"] = True
    else:
        reasons.append("initial_skills_not_empty")

    if not output.exists() or all(
        child.name in _ALLOWED_OUTPUT_ENTRIES for child in output.iterdir()
    ):
        checks["output_isolated"] = True
    else:
        reasons.append("output_collision")

    reasons = list(dict.fromkeys(reasons))
    return SkillFlowPreflightReport(
        schema_version="rsebench.skillflow-preflight.v1",
        status="ready" if not reasons else "blocked",
        checked_at=datetime.now(timezone.utc),
        provider_calls=0,
        checks=checks,
        reasons=reasons,
        baseline_fingerprint=(
            str(baseline_payload["fingerprint"])
            if baseline_payload is not None and "fingerprint" in baseline_payload
            else None
        ),
        docker_image=config.runtime.docker_image,
        docker_image_digest=image_digest,
        input_manifest_hash=canonical_hash(manifest),
    )


def _candidate_families(
    phase: Phase,
    manifest: SkillFlowInputManifest,
    selected_families: Sequence[str] | None,
) -> tuple[list[str], list[ReplicateId]]:
    if phase == "screen":
        return list(
            manifest.batch_a if selected_families is None else selected_families
        ), ["r1"]
    if not selected_families:
        raise ValueError("confirm requires preliminary-positive families")
    return list(selected_families), ["r2", "r3"]


def plan_attempt(
    *,
    phase: Phase,
    attempt_id: str,
    project_root: Path | str,
    method_root: Path | str,
    output_root: Path | str,
    config: SkillFlowCleanConfig,
    manifest: SkillFlowInputManifest,
    dry_run: bool,
    selected_families: Sequence[str] | None = None,
    missing_replicates: Mapping[str, Sequence[ReplicateId]] | None = None,
    python: str | None = None,
) -> SkillFlowRunManifest:
    """Persist one immutable execution plan before any provider call."""

    project = Path(project_root).resolve()
    method = Path(method_root).resolve()
    output = Path(output_root).resolve()
    attempt_root = output / "attempts" / attempt_id
    if attempt_root.exists():
        raise FileExistsError(f"attempt already exists: {attempt_root}")
    attempt_root.mkdir(parents=True)
    if canonical_hash(config) != manifest.config_hash:
        raise ValueError("config differs from frozen SkillFlow input manifest")
    data_root = Path(config.data_root)
    if not data_root.is_absolute():
        data_root = (project / data_root).resolve()
    families, replicates = _candidate_families(
        phase, manifest, selected_families
    )
    by_family = {item.family: item for item in manifest.families}
    unknown = [family for family in families if family not in by_family]
    if unknown:
        raise ValueError(f"unknown SkillFlow candidate families: {unknown}")

    arms: list[SkillFlowArmPlan] = []
    input_invalid: dict[str, list[str]] = {}
    interpreter = python or str(method / ".venv/bin/python")
    for family_name in families:
        family = by_family[family_name]
        if family.status != "ready":
            input_invalid[family_name] = list(family.invalid_reasons)
            continue
        family_path = data_root / family_name
        family_replicates = list(
            missing_replicates.get(family_name, replicates)
            if missing_replicates is not None
            else replicates
        )
        if any(item not in replicates for item in family_replicates):
            raise ValueError(
                f"invalid {phase} replicate selection for {family_name}: "
                f"{family_replicates}"
            )
        for replicate_id in family_replicates:
            for arm in ("base", "clean_evolution"):
                arm_name: ArmName = arm
                config_path = (
                    attempt_root / "configs" / family_name / replicate_id / f"{arm}.yaml"
                )
                arm_root = attempt_root / "families" / family_name / replicate_id / arm
                native = build_native_config(
                    config,
                    family=family_name,
                    family_path=family_path,
                    replicate_id=replicate_id,
                    arm=arm_name,
                )
                _write_yaml(config_path, native)
                job_arm = "evolution" if arm == "clean_evolution" else "base"
                job_name = f"skillflow-{job_arm}-{replicate_id}__{family_name}"
                job_dir = arm_root / job_name
                arms.append(
                    SkillFlowArmPlan(
                        family=family_name,
                        replicate_id=replicate_id,
                        arm=arm_name,
                        config_path=str(config_path),
                        arm_root=str(arm_root),
                        job_dir=str(job_dir),
                        command=build_arm_command(
                            python=interpreter,
                            method_root=method,
                            config_path=config_path,
                            family=family_name,
                            family_path=family_path,
                            arm_root=arm_root,
                            arm=arm_name,
                            runtime=config.runtime,
                        ),
                    )
                )
    run_manifest = SkillFlowRunManifest(
        schema_version="rsebench.skillflow-run.v1",
        attempt_id=attempt_id,
        phase=phase,
        created_at=datetime.now(timezone.utc),
        dry_run=dry_run,
        provider_calls=0,
        project_root=str(project),
        method_root=str(method),
        output_root=str(output),
        config_hash=manifest.config_hash,
        input_manifest_hash=canonical_hash(manifest),
        families=families,
        input_invalid_families=input_invalid,
        arms=arms,
    )
    _write_json(attempt_root / "run_manifest.json", run_manifest)
    return run_manifest


def _runtime_environment(
    *, arm_plan: SkillFlowArmPlan, attempt: SkillFlowRunManifest
) -> dict[str, str]:
    from scripts.baselines.common_env import combined_method_env

    environment = combined_method_env("skillflow")
    deepseek_key = environment.get("DEEPSEEK_API_KEY", "").strip()
    if not deepseek_key:
        raise RuntimeError("DEEPSEEK_API_KEY is empty")
    environment["OPENAI_API_KEY"] = deepseek_key
    environment["OPENAI_API_BASE"] = "https://api.deepseek.com/v1"
    environment["PYTHONUNBUFFERED"] = "1"
    stage = "worker" if arm_plan.arm == "base" else "worker_and_patcher"
    return token_context_environment(
        environment,
        ledger_dir=Path(arm_plan.job_dir) / "token_usage",
        run_id=attempt.attempt_id,
        domain="skill_native",
        benchmark="skillflow_tasks",
        arm=arm_plan.arm,
        stage=stage,
    )


def execute_attempt(
    attempt: SkillFlowRunManifest,
    *,
    config: SkillFlowCleanConfig,
    manifest: SkillFlowInputManifest,
) -> list[SkillFlowReplicateResult]:
    """Execute a prewritten plan serially and persist paired compact evidence."""

    if attempt.dry_run:
        return []
    attempt_root = Path(attempt.output_root) / "attempts" / attempt.attempt_id
    recorder = TimingRecorder(attempt_root)
    by_pair: dict[tuple[str, str], dict[str, SkillFlowArmPlan]] = {}
    for arm in attempt.arms:
        by_pair.setdefault((arm.family, arm.replicate_id), {})[arm.arm] = arm
    family_manifest = {family.family: family for family in manifest.families}
    paired_results: list[SkillFlowReplicateResult] = []
    caught: BaseException | None = None
    try:
        with recorder.span(level="run", name=f"skillflow_{attempt.phase}"):
            for (family, replicate_id), plans in by_pair.items():
                arm_results = {}
                for arm_name in ("base", "clean_evolution"):
                    arm_plan = plans[arm_name]
                    arm_root = Path(arm_plan.arm_root)
                    if arm_root.exists():
                        raise FileExistsError(f"arm output collision: {arm_root}")
                    log_root = attempt_root / "logs" / family / replicate_id
                    log_root.mkdir(parents=True, exist_ok=True)
                    with recorder.span(
                        level="stage",
                        name=f"{family}:{replicate_id}:{arm_name}",
                        metadata={"family": family, "replicate_id": replicate_id, "arm": arm_name},
                    ):
                        completed = subprocess.run(
                            arm_plan.command,
                            cwd=attempt.method_root,
                            env=_runtime_environment(arm_plan=arm_plan, attempt=attempt),
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=config.runtime.arm_timeout_seconds,
                        )
                        (log_root / f"{arm_name}.stdout.log").write_text(
                            completed.stdout, encoding="utf-8"
                        )
                        (log_root / f"{arm_name}.stderr.log").write_text(
                            completed.stderr, encoding="utf-8"
                        )
                        if completed.returncode:
                            raise SkillFlowExecutionError(
                                f"{family}/{replicate_id}/{arm_name} exited "
                                f"{completed.returncode}; see {log_root}"
                            )
                    arm_result = parse_arm_result(
                        arm_plan.job_dir,
                        family_manifest[family],
                        arm=arm_name,
                        replicate_id=replicate_id,
                    )
                    _write_json(
                        Path(arm_plan.arm_root) / "rsebench_arm_result.json", arm_result
                    )
                    arm_results[arm_name] = arm_result
                paired = pair_replicate(
                    arm_results["base"], arm_results["clean_evolution"]
                )
                paired_path = (
                    attempt_root
                    / "families"
                    / family
                    / replicate_id
                    / "paired_result.json"
                )
                _write_json(paired_path, paired)
                paired_results.append(paired)
    except BaseException as exc:
        caught = exc
    finally:
        try:
            recorder.finalize()
        except BaseException as timing_exc:
            if caught is None:
                caught = timing_exc
    if caught is not None:
        raise caught
    _write_json(
        attempt_root / "run_result.json",
        {
            "schema_version": "rsebench.skillflow-run-result.v1",
            "attempt_id": attempt.attempt_id,
            "provider_calls": sum(
                result.base.token_usage.attempted_calls
                + result.evolution.token_usage.attempted_calls
                for result in paired_results
            ),
            "paired_results": [
                result.model_dump(mode="json") for result in paired_results
            ],
        },
    )
    return paired_results


def _preliminary_reasons(result: SkillFlowReplicateResult) -> list[str]:
    reasons: list[str] = []
    if not result.complete:
        return [f"invalid_replicate:{result.replicate_id}"]
    if result.delta_late is None or result.delta_late <= 0:
        reasons.append("late_delta_not_positive")
    if result.evolution.nonempty_patch_count == 0:
        reasons.append("missing_nonempty_patch")
    if result.evolution.skill_used_task_count == 0:
        reasons.append("missing_later_skill_use")
    return reasons


def aggregate_evidence(
    manifest: SkillFlowInputManifest,
    replicates_by_family: Mapping[str, Sequence[SkillFlowReplicateResult]],
) -> SkillFlowAggregate:
    families: list[SkillFlowFamilyAggregate] = []
    provider_calls = 0
    for frozen in manifest.families:
        replicates = list(replicates_by_family.get(frozen.family, []))
        for item in replicates:
            provider_calls += item.base.token_usage.attempted_calls
            provider_calls += item.evolution.token_usage.attempted_calls
        if frozen.status == "invalid":
            families.append(
                SkillFlowFamilyAggregate(
                    family=frozen.family,
                    status="input_invalid",
                    reasons=list(frozen.invalid_reasons),
                    preliminary_positive=False,
                    replicates=replicates,
                    decision=None,
                )
            )
            continue
        if not replicates:
            families.append(
                SkillFlowFamilyAggregate(
                    family=frozen.family,
                    status="unscreened",
                    reasons=[],
                    preliminary_positive=False,
                    replicates=[],
                    decision=None,
                )
            )
            continue
        if len(replicates) == 1 and replicates[0].replicate_id == "r1":
            preliminary = is_preliminary_positive(replicates[0])
            families.append(
                SkillFlowFamilyAggregate(
                    family=frozen.family,
                    status="preliminary_positive" if preliminary else (
                        "incomplete" if not replicates[0].complete else "screened_out"
                    ),
                    reasons=[] if preliminary else _preliminary_reasons(replicates[0]),
                    preliminary_positive=preliminary,
                    replicates=replicates,
                    decision=None,
                )
            )
            continue
        decision = qualify_family(replicates)
        families.append(
            SkillFlowFamilyAggregate(
                family=frozen.family,
                status=decision.status,
                reasons=list(decision.reasons),
                preliminary_positive=any(
                    item.replicate_id == "r1" and is_preliminary_positive(item)
                    for item in replicates
                ),
                replicates=replicates,
                decision=decision,
            )
        )
    return SkillFlowAggregate(
        schema_version="rsebench.skillflow-aggregate.v1",
        created_at=datetime.now(timezone.utc),
        input_manifest_hash=canonical_hash(manifest),
        provider_calls=provider_calls,
        families=families,
    )


def aggregate_results(
    *, output_root: Path | str, manifest: SkillFlowInputManifest
) -> SkillFlowAggregate:
    output = Path(output_root).resolve()
    by_family: dict[str, list[SkillFlowReplicateResult]] = {}
    for path in sorted((output / "attempts").glob("*/families/*/*/paired_result.json")):
        result = SkillFlowReplicateResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        by_family.setdefault(result.family, []).append(result)
    aggregate = aggregate_evidence(manifest, by_family)
    _write_json(output / "aggregate.json", aggregate)
    return aggregate


def select_batch_b_families(
    aggregate: SkillFlowAggregate, manifest: SkillFlowInputManifest
) -> list[str]:
    """Open Batch B only after Batch A completes with fewer than two signals."""

    by_family = {family.family: family for family in aggregate.families}
    incomplete = [
        family
        for family in manifest.batch_a
        if by_family[family].status == "unscreened"
    ]
    if incomplete:
        raise RuntimeError(f"Batch A screening is incomplete: {incomplete}")
    positives = sum(
        by_family[family].preliminary_positive for family in manifest.batch_a
    )
    if positives >= manifest.qualification.target_qualified_families:
        raise RuntimeError(
            "Batch B is not permitted after Batch A produced enough "
            "preliminary-positive families"
        )
    return list(manifest.batch_b)


def select_confirmation_families(
    aggregate: SkillFlowAggregate,
    manifest: SkillFlowInputManifest,
    requested: Sequence[str] | None,
) -> list[str]:
    """Select candidate-order preliminary positives and reject outcome fishing."""

    by_family = {family.family: family for family in aggregate.families}
    candidates = list(requested) if requested is not None else [
        family
        for family in [*manifest.batch_a, *manifest.batch_b]
        if by_family[family].preliminary_positive
    ][: manifest.qualification.target_qualified_families]
    invalid = [
        family
        for family in candidates
        if family not in by_family or not by_family[family].preliminary_positive
    ]
    if invalid:
        raise ValueError(f"not preliminary-positive families: {invalid}")
    if not candidates:
        raise RuntimeError("no preliminary-positive SkillFlow families to confirm")
    return candidates


def freeze_qualified(
    *,
    aggregate: SkillFlowAggregate,
    manifest: SkillFlowInputManifest,
    data_root: Path | str,
    output_path: Path | str,
) -> dict[str, Any]:
    """Freeze compact machine evidence only after two families clear the fixed gate."""

    verify_input_manifest(manifest, data_root=data_root)
    if aggregate.input_manifest_hash != canonical_hash(manifest):
        raise RuntimeError("aggregate belongs to a different SkillFlow input manifest")
    qualified = [family for family in aggregate.families if family.status == "qualified"]
    target = manifest.qualification.target_qualified_families
    if len(qualified) < target:
        raise RuntimeError(f"cannot freeze SkillFlow: {len(qualified)}/{target} families qualify")
    selected_names = {
        family.family
        for family in qualified[:target]
    }
    selected_inputs = [
        family.model_dump(mode="json")
        for family in manifest.families
        if family.family in selected_names
    ]
    selected_evidence = [
        family.model_dump(mode="json")
        for family in aggregate.families
        if family.family in selected_names
    ]
    payload = {
        "schema_version": "rsebench.skillflow-frozen-clean.v1",
        "benchmark": manifest.benchmark,
        "baseline": manifest.baseline,
        "upstream_revision": manifest.upstream_revision,
        "qualification_contract": manifest.qualification_contract,
        "input_manifest_hash": canonical_hash(manifest),
        "provider_calls": aggregate.provider_calls,
        "qualified_families": [
            family.family for family in manifest.families if family.family in selected_names
        ],
        "families": selected_inputs,
        "evidence": selected_evidence,
    }
    target_path = Path(output_path)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target_path.exists() and target_path.read_text(encoding="utf-8") != encoded:
        raise FileExistsError(f"different frozen SkillFlow manifest exists: {target_path}")
    if not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(encoded, encoding="utf-8")
    return payload


__all__ = [
    "SkillFlowAggregate",
    "SkillFlowArmPlan",
    "SkillFlowExecutionError",
    "SkillFlowFamilyAggregate",
    "SkillFlowPreflightReport",
    "SkillFlowRunManifest",
    "aggregate_evidence",
    "aggregate_results",
    "build_arm_command",
    "build_native_config",
    "execute_attempt",
    "freeze_qualified",
    "plan_attempt",
    "run_preflight",
    "select_batch_b_families",
    "select_confirmation_families",
    "validate_provider_cost",
]
