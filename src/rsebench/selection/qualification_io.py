"""Filesystem-owned evidence discovery for stable split qualification."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from rsebench.contracts import StrictModel
from rsebench.evidence import canonical_hash
from rsebench.experiments.contracts import ExperimentIdentity
from rsebench.hashing import sha256_file
from rsebench.selection.contracts import (
    CandidateSeedEvidence,
    DomainSelectionStatus,
    ScreeningSeedEvidence,
    SelectionStatus,
    StableSplitCandidate,
)
from rsebench.selection.qualification import (
    DomainScreeningGeneralization,
    ScreeningGeneralizationAggregate,
    decide_candidate,
    decide_screening_generalization,
    replay_action,
    replay_integrity_failures,
    select_candidate_evaluation_tasks,
    sequential_incomplete_action,
)


METHOD_SEEDS = (20260813, 20260814, 20260815)
POOL_BENCHMARKS = (
    "spreadsheetbench_verified",
    "officeqa_full",
    "webshop",
)
SKILLLEARN_FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
)
_POOL_COUNTS = {
    "spreadsheetbench_verified": (20, 10, 30, 30),
    "officeqa_full": (12, 12, 20, 20),
    "webshop": (5, 5, 20, 20),
}


@dataclass(frozen=True)
class SelectionRepository:
    root: Path
    candidates: dict[str, dict[int, StableSplitCandidate]]
    candidate_paths: dict[tuple[str, int], Path]
    audits: dict[tuple[str, int], dict[str, Any]]


class CleanRunEvidence(StrictModel):
    benchmark: str
    candidate_index: int = Field(ge=1, le=3)
    selection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    family: str | None = None
    method_seed: int
    run_dir: str
    train_task_ids: list[str]
    validation_task_ids: list[str]
    accepted_update_count: int = Field(ge=0)
    artifact_changed: bool
    validation_complete: bool
    seed_artifact_path: str
    seed_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    clean_artifact_path: str
    clean_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evolution_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    model: str
    provider_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace_applicability: dict[str, Any] = Field(default_factory=dict)
    domain_audit: dict[str, Any] = Field(default_factory=dict)
    failure_reasons: list[str] = Field(default_factory=list)


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _inside(root: Path, raw: str) -> Path:
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"selection path escapes root: {raw}") from exc
    return candidate


def _ids(tasks: list[Any]) -> list[str]:
    return [task.task_id for task in tasks]


def _same_unique_ids(actual: list[str], expected: list[str]) -> bool:
    return (
        len(actual) == len(expected)
        and len(actual) == len(set(actual))
        and set(actual) == set(expected)
    )


def validate_candidate_denominators(candidate: StableSplitCandidate) -> None:
    """Reject reduced or role-substituted pools before any result is considered."""

    if candidate.benchmark in _POOL_COUNTS:
        actual = tuple(
            len(getattr(candidate, role))
            for role in (
                "train",
                "validation",
                "qualification_test",
                "screening_test",
            )
        )
        if actual != _POOL_COUNTS[candidate.benchmark]:
            raise ValueError(
                f"{candidate.benchmark} candidate has wrong fixed denominator: {actual}"
            )
        return
    if candidate.benchmark != "skilllearnbench":
        raise ValueError(f"unsupported selection benchmark: {candidate.benchmark}")
    if candidate.candidate_index != 1 or candidate.qualification_test:
        raise ValueError("SkillLearn uses one fixed candidate without qualification test")
    families = candidate.metadata.get("families")
    if list(families or []) != list(SKILLLEARN_FAMILIES):
        raise ValueError("SkillLearn candidate must retain four fixed screening families")
    if len(candidate.train) != 8 or len(candidate.validation) != 4:
        raise ValueError("SkillLearn candidate requires exactly 8/4 acquisition roles")
    all_tasks = [
        *candidate.train,
        *candidate.validation,
        *candidate.screening_test,
    ]
    if any(
        task.metadata.get("task_family") not in SKILLLEARN_FAMILIES
        for task in all_tasks
    ):
        raise ValueError("SkillLearn candidate contains a substituted family")
    for family in SKILLLEARN_FAMILIES:
        train = [task for task in candidate.train if task.metadata.get("task_family") == family]
        validation = [
            task
            for task in candidate.validation
            if task.metadata.get("task_family") == family
        ]
        screening = [
            task
            for task in candidate.screening_test
            if task.metadata.get("task_family") == family
        ]
        if (len(train), len(validation), len(screening)) not in {(2, 1, 2), (2, 1, 3)}:
            raise ValueError(f"SkillLearn family allocation has wrong denominator: {family}")
        select_candidate_evaluation_tasks(
            candidate,
            evaluation_role="screening_test",
            family=family,
        )


def load_selection_repository(root: Path | str) -> SelectionRepository:
    selection_root = Path(root).resolve()
    manifest = _read_object(selection_root / "manifest.json")
    candidate_index = manifest.get("candidates")
    audit_index = manifest.get("candidate_audits")
    if not isinstance(candidate_index, dict) or not isinstance(audit_index, dict):
        raise ValueError("selection manifest lacks candidate indexes")
    expected = {*POOL_BENCHMARKS, "skilllearnbench"}
    if set(candidate_index) != expected or set(audit_index) != expected:
        raise ValueError("selection manifest requires exactly four benchmarks")
    candidates: dict[str, dict[int, StableSplitCandidate]] = {}
    paths: dict[tuple[str, int], Path] = {}
    audits: dict[tuple[str, int], dict[str, Any]] = {}
    for benchmark in sorted(expected):
        candidate_paths = candidate_index[benchmark]
        audit_paths = audit_index[benchmark]
        if not isinstance(candidate_paths, list) or not isinstance(audit_paths, list):
            raise ValueError(f"malformed candidate index: {benchmark}")
        if len(candidate_paths) != len(audit_paths):
            raise ValueError(f"candidate/audit count differs: {benchmark}")
        candidates[benchmark] = {}
        for raw_candidate, raw_audit in zip(candidate_paths, audit_paths, strict=True):
            path = _inside(selection_root, str(raw_candidate))
            audit_path = _inside(selection_root, str(raw_audit))
            candidate = StableSplitCandidate.model_validate(_read_object(path))
            if candidate.benchmark != benchmark:
                raise ValueError(f"candidate benchmark differs from index: {path}")
            validate_candidate_denominators(candidate)
            audit = _read_object(audit_path)
            if (
                audit.get("benchmark") != benchmark
                or audit.get("candidate_index") != candidate.candidate_index
                or audit.get("selection_hash") != candidate.selection_hash
            ):
                raise ValueError(f"candidate audit identity differs: {audit_path}")
            if candidate.candidate_index in candidates[benchmark]:
                raise ValueError(f"duplicate candidate index: {benchmark}")
            candidates[benchmark][candidate.candidate_index] = candidate
            paths[(benchmark, candidate.candidate_index)] = path
            audits[(benchmark, candidate.candidate_index)] = audit
    for benchmark in POOL_BENCHMARKS:
        if set(candidates[benchmark]) != {1, 2, 3}:
            raise ValueError(f"pool benchmark requires Candidates 1-3: {benchmark}")
    if set(candidates["skilllearnbench"]) != {1}:
        raise ValueError("SkillLearn requires exactly Candidate 1")
    return SelectionRepository(selection_root, candidates, paths, audits)


def _find_runtime_identity(run_dir: Path, boundary: Path) -> Path:
    for parent in (run_dir, *run_dir.parents):
        candidate = parent / "runtime_identity.json"
        if candidate.is_file():
            return candidate
        if parent == boundary:
            break
    raise FileNotFoundError(f"runtime_identity.json not found above {run_dir}")


def _artifact_path(run_dir: Path, raw: str) -> Path:
    candidate = Path(raw)
    return (candidate if candidate.is_absolute() else run_dir / candidate).resolve()


def _clean_accounting_failures(result: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    timing = result.get("timing")
    if not isinstance(timing, dict):
        reasons.append("missing_clean_timing")
    else:
        if not isinstance(timing.get("run"), dict):
            reasons.append("missing_clean_run_timing")
        if not isinstance(timing.get("stages"), list) or not timing["stages"]:
            reasons.append("missing_clean_stage_timing")
        if not isinstance(timing.get("tasks"), list) or not timing["tasks"]:
            reasons.append("missing_clean_task_timing")
    usage = result.get("token_usage")
    if not isinstance(usage, dict):
        reasons.append("missing_clean_token_usage")
    else:
        billed = usage.get("billed_tokens")
        if not isinstance(billed, dict) or any(
            field not in billed
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        ):
            reasons.append("missing_clean_token_totals")
        if usage.get("observed_coverage") != 1.0:
            reasons.append("incomplete_clean_token_observation")
    return reasons


def _match_candidate(
    repository: SelectionRepository,
    split: dict[str, Any],
) -> tuple[StableSplitCandidate, int, str | None]:
    benchmark = str(split.get("benchmark") or "")
    metadata = split.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    family = str(metadata.get("task_family") or "") or None
    declared = metadata.get("candidate_index")
    indexes = [int(declared)] if declared is not None else sorted(repository.candidates[benchmark])
    for index in indexes:
        candidate = repository.candidates[benchmark].get(index)
        if candidate is None:
            continue
        if family:
            allocation = candidate.metadata.get("static_audit", {}).get(
                "family_allocations", {}
            ).get(family, {})
            expected_train = allocation.get("train")
            expected_validation = allocation.get("validation")
        else:
            expected_train = _ids(candidate.train)
            expected_validation = _ids(candidate.validation)
        if (
            [row["task_id"] for row in split.get("train", [])] == expected_train
            and [row["task_id"] for row in split.get("validation", [])]
            == expected_validation
        ):
            parent_hash = metadata.get("parent_selection_hash")
            if parent_hash is not None and parent_hash != candidate.selection_hash:
                raise ValueError("run split parent selection hash differs")
            return candidate, index, family
    raise ValueError(f"clean run tasks do not match a frozen candidate: {benchmark}")


def read_clean_run(
    run_dir: Path,
    *,
    repository: SelectionRepository,
    boundary: Path,
) -> CleanRunEvidence:
    split = _read_object(run_dir / "split_manifest.json")
    candidate, candidate_index, family = _match_candidate(repository, split)
    result = _read_object(run_dir / "result.json")
    qualification = _read_object(run_dir / "qualification.json")
    artifact = _read_object(run_dir / "clean/evolution_artifact.json")
    runtime = _read_object(_find_runtime_identity(run_dir, boundary))
    identity = ExperimentIdentity.model_validate(runtime.get("identity"))
    result_identity = result.get("identity")
    if not isinstance(result_identity, dict) or result_identity.get(
        "experiment_id"
    ) != identity.experiment_id:
        raise ValueError("clean result/runtime identity mismatch")
    method_seed = int(result.get("method_seed", -1))
    if method_seed != identity.inputs.method_seed:
        raise ValueError("clean result method seed differs from runtime identity")
    seed_files = [path for path in (run_dir / "seed").iterdir() if path.is_file()]
    if len(seed_files) != 1:
        raise ValueError("clean run requires exactly one seed artifact")
    seed_path = seed_files[0].resolve()
    seed_hash = sha256_file(seed_path)
    clean_path = _artifact_path(run_dir, str(artifact.get("skill_path") or ""))
    if not clean_path.is_file():
        raise FileNotFoundError(f"clean artifact is missing: {clean_path}")
    clean_hash = sha256_file(clean_path)
    if clean_hash != artifact.get("skill_hash") or clean_hash != result.get(
        "clean_skill_hash"
    ):
        raise ValueError("clean artifact hash differs from recorded result")
    execution = artifact.get("execution_audit")
    if not isinstance(execution, dict):
        raise ValueError("clean artifact lacks execution audit")
    train_ids = list(execution.get("train_task_ids") or [])
    validation_ids = list(execution.get("validation_task_ids") or [])
    if family:
        allocation = candidate.metadata["static_audit"]["family_allocations"][family]
        expected_train = list(allocation["train"])
        expected_validation = list(allocation["validation"])
    else:
        expected_train = _ids(candidate.train)
        expected_validation = _ids(candidate.validation)
    failures = _clean_accounting_failures(result)
    accepted_update_count = int(execution.get("accepted_update_count", 0))
    if qualification.get("accepted_update_count") != accepted_update_count:
        failures.append("qualification_update_count_differs")
    if qualification.get("artifact_updated") != (clean_hash != seed_hash):
        failures.append("qualification_artifact_state_differs")
    if qualification.get("execution_coverage_passed") is not True:
        failures.append("qualification_execution_coverage_failed")
    if qualification.get("runtime_gates_passed") is not True:
        failures.append("qualification_runtime_gates_failed")
    if not _same_unique_ids(train_ids, expected_train):
        failures.append("clean_train_execution_set_differs")
    if not _same_unique_ids(validation_ids, expected_validation):
        failures.append("clean_validation_execution_set_differs")
    inputs = identity.inputs.model_dump(mode="json")
    provider_config_hash = inputs["runtime"].get("provider_config_hash")
    if not isinstance(provider_config_hash, str):
        failures.append("missing_provider_config_hash")
        provider_config_hash = "0" * 64
    if identity.inputs.provider != "deepseek" or identity.inputs.model != "deepseek-v4-flash":
        failures.append("provider_or_model_differs")
    if seed_hash != identity.inputs.seed_skill_hash or seed_hash != result.get(
        "seed_skill_hash"
    ):
        failures.append("seed_artifact_hash_differs")
    scope = {
        key: value
        for key, value in inputs.items()
        if key not in {"method_seed", "repository_commit"}
    }
    scope["selection_hash"] = candidate.selection_hash
    scope["family"] = family
    trace_path = run_dir / "trace_applicability.json"
    domain_path = run_dir / "domain_audit.json"
    return CleanRunEvidence(
        benchmark=candidate.benchmark,
        candidate_index=candidate_index,
        selection_hash=candidate.selection_hash,
        family=family,
        method_seed=method_seed,
        run_dir=str(run_dir.resolve()),
        train_task_ids=train_ids,
        validation_task_ids=validation_ids,
        accepted_update_count=accepted_update_count,
        artifact_changed=clean_hash != seed_hash,
        validation_complete=_same_unique_ids(validation_ids, expected_validation),
        seed_artifact_path=str(seed_path),
        seed_artifact_hash=seed_hash,
        clean_artifact_path=str(clean_path),
        clean_artifact_hash=clean_hash,
        baseline_fingerprint=identity.inputs.baseline.fingerprint,
        evolution_input_hash=canonical_hash(scope),
        provider=identity.inputs.provider,
        model=identity.inputs.model,
        provider_config_hash=provider_config_hash,
        trace_applicability=(
            _read_object(trace_path) if trace_path.is_file() else {}
        ),
        domain_audit=_read_object(domain_path) if domain_path.is_file() else {},
        failure_reasons=failures,
    )


def discover_clean_runs(
    root: Path | str,
    repository: SelectionRepository,
) -> list[CleanRunEvidence]:
    boundary = Path(root).resolve()
    if not boundary.exists():
        return []
    records: list[CleanRunEvidence] = []
    for qualification in sorted(boundary.rglob("qualification.json")):
        run_dir = qualification.parent
        required = (
            run_dir / "result.json",
            run_dir / "split_manifest.json",
            run_dir / "clean/evolution_artifact.json",
        )
        if not all(path.is_file() for path in required):
            continue
        try:
            records.append(
                read_clean_run(run_dir, repository=repository, boundary=boundary)
            )
        except (KeyError, TypeError, ValueError, FileNotFoundError):
            continue
    return records


def _group_failures(
    candidate: StableSplitCandidate,
    runs: list[CleanRunEvidence],
    *,
    family: str | None,
) -> list[str]:
    failures: list[str] = []
    if len(runs) != 3 or {run.method_seed for run in runs} != set(METHOD_SEEDS):
        failures.append("missing_exact_three_method_seeds")
    invariant_fields = (
        "baseline_fingerprint",
        "evolution_input_hash",
        "provider",
        "model",
        "provider_config_hash",
    )
    for field in invariant_fields:
        if len({getattr(run, field) for run in runs}) > 1:
            failures.append(f"mixed_clean_identity:{field}")
    for run in runs:
        failures.extend(run.failure_reasons)
        if run.selection_hash != candidate.selection_hash:
            failures.append("run_selection_hash_differs")
        if run.family != family:
            failures.append("run_family_substituted")
    return list(dict.fromkeys(failures))


def _applicability_rows(audit: dict[str, Any]) -> dict[str, Any]:
    static_gates = audit.get("static_gates")
    if isinstance(static_gates, dict):
        rows = static_gates.get("noise_applicability")
        if isinstance(rows, dict):
            return rows
    rows = audit.get("noise_applicability")
    return rows if isinstance(rows, dict) else {}


def _selection_audit_failures(
    repository: SelectionRepository,
    candidate: StableSplitCandidate,
    runs: list[CleanRunEvidence],
) -> list[str]:
    """Require static, trace-derived, and domain gates from owned evidence."""

    failures: list[str] = []
    static_rows = _applicability_rows(
        repository.audits[(candidate.benchmark, candidate.candidate_index)]
    )
    for stage in ("N1", "N2"):
        row = static_rows.get(stage)
        if not isinstance(row, dict):
            failures.append(f"missing_noise_applicability:{stage}")
        elif row.get("status") != "pass" or row.get("coverage") != 1.0:
            failures.append(f"incomplete_noise_applicability:{stage}")
    for run in runs:
        for stage in ("N3", "N4"):
            row = run.trace_applicability.get(stage)
            if not isinstance(row, dict):
                failures.append(f"missing_noise_applicability:{stage}")
            elif row.get("status") == "pending":
                failures.append(f"pending_noise_applicability:{stage}")
            elif row.get("status") != "pass" or row.get("coverage") != 1.0:
                failures.append(f"incomplete_noise_applicability:{stage}")
        if not run.domain_audit:
            failures.append("missing_domain_audit")
        elif run.domain_audit.get("passed") is not True:
            reasons = run.domain_audit.get("failure_reasons")
            if isinstance(reasons, list) and reasons:
                failures.extend(str(reason) for reason in reasons)
            else:
                failures.append("domain_structural_audit_failed")
    return list(dict.fromkeys(failures))


def _replay_result_path(
    run_root: Path,
    *,
    role: str,
    benchmark: str,
    candidate_index: int,
    method_seed: int,
    family: str | None,
) -> Path:
    key = family or "domain"
    return (
        run_root
        / "replays"
        / role
        / benchmark
        / f"candidate_{candidate_index}"
        / key
        / str(method_seed)
        / "result.json"
    )


def _load_replay(
    path: Path,
    *,
    candidate: StableSplitCandidate,
    run: CleanRunEvidence,
    evaluation_role: Literal["qualification_test", "screening_test"],
) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.is_file():
        return None, ["missing_replay_result"]
    replay = _read_object(path)
    failures = replay_integrity_failures(replay)
    expected_tasks = select_candidate_evaluation_tasks(
        candidate,
        evaluation_role=evaluation_role,
        family=run.family,
    )
    expected_ids = _ids(expected_tasks)
    if replay.get("task_ids") != expected_ids:
        failures.append("replay_task_ids_differ_from_frozen_role")
    expected_task_hash = canonical_hash(
        [task.model_dump(mode="json") for task in expected_tasks]
    )
    if replay.get("task_manifest_hash") != expected_task_hash:
        failures.append("replay_task_manifest_hash_differs")
    hashes = replay.get("artifact_hashes")
    expected_hashes = {
        "seed": run.seed_artifact_hash,
        "clean": run.clean_artifact_hash,
    }
    if hashes != expected_hashes:
        failures.append("replay_artifact_hashes_differ")
    if replay.get("reference_label") != "seed":
        failures.append("replay_reference_is_not_seed")
    return replay, list(dict.fromkeys(failures))


def _candidate_result(
    *,
    repository: SelectionRepository,
    candidate: StableSplitCandidate,
    runs: list[CleanRunEvidence],
    run_root: Path,
    family: str | None = None,
) -> tuple[str, list[str]]:
    group_failures = [
        *_group_failures(candidate, runs, family=family),
        *_selection_audit_failures(repository, candidate, runs),
    ]
    if group_failures:
        return sequential_incomplete_action(candidate.candidate_index), group_failures
    seed_evidence: list[CandidateSeedEvidence] = []
    replay_failures: list[str] = []
    extend = False
    for run in sorted(runs, key=lambda item: item.method_seed):
        replay, failures = _load_replay(
            _replay_result_path(
                run_root,
                role="qualification_test",
                benchmark=candidate.benchmark,
                candidate_index=candidate.candidate_index,
                method_seed=run.method_seed,
                family=family,
            ),
            candidate=candidate,
            run=run,
            evaluation_role="qualification_test",
        )
        replay_failures.extend(failures)
        if replay is None or failures:
            continue
        clean_summary = replay["summaries"]["clean"]
        deltas = [float(value) for value in clean_summary["deltas_vs_reference"]]
        if replay_action(deltas, repeats=int(replay["repeat_count"])) == (
            "extend_replay_to_5"
        ):
            extend = True
        seed_evidence.append(
            CandidateSeedEvidence(
                method_seed=run.method_seed,
                accepted_update_count=run.accepted_update_count,
                artifact_changed=run.artifact_changed,
                mean_delta_vs_seed=float(clean_summary["mean_delta_vs_reference"]),
                execution_complete=True,
                replay_count=int(replay["repeat_count"]),
            )
        )
    if replay_failures:
        return sequential_incomplete_action(candidate.candidate_index), list(
            dict.fromkeys(replay_failures)
        )
    if extend:
        return "extend_replay_to_5", ["sign_inconsistent_three_repeat_replay"]
    decision = decide_candidate(
        candidate_index=candidate.candidate_index,
        seeds=seed_evidence,
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    return decision.next_action, decision.failure_reasons


def _records_for(
    records: list[CleanRunEvidence],
    benchmark: str,
    candidate_index: int,
    family: str | None = None,
) -> list[CleanRunEvidence]:
    return [
        record
        for record in records
        if record.benchmark == benchmark
        and record.candidate_index == candidate_index
        and record.family == family
    ]


def _overlay_reused_records(
    primary: list[CleanRunEvidence],
    reused: list[CleanRunEvidence],
) -> list[CleanRunEvidence]:
    """Prefer newly executed evidence without hiding duplicate primary attempts."""

    occupied = {
        (row.benchmark, row.candidate_index, row.family, row.method_seed)
        for row in primary
    }
    return [
        *primary,
        *[
            row
            for row in reused
            if (row.benchmark, row.candidate_index, row.family, row.method_seed)
            not in occupied
        ],
    ]


def _pool_qualification_status(
    repository: SelectionRepository,
    records: list[CleanRunEvidence],
    run_root: Path,
    benchmark: str,
) -> DomainSelectionStatus:
    start = 2 if benchmark == "spreadsheetbench_verified" else 1
    for index in range(start, 4):
        candidate = repository.candidates[benchmark][index]
        runs = _records_for(records, benchmark, index)
        action, reasons = _candidate_result(
            repository=repository,
            candidate=candidate,
            runs=runs,
            run_root=run_root,
        )
        if action == "freeze_candidate":
            return DomainSelectionStatus(
                benchmark=benchmark,
                selected_candidate_index=index,
                next_action="freeze_candidate",
                reasons=[],
            )
        if action == "run_candidate_2" and index == 1:
            if _records_for(records, benchmark, 2):
                continue
            return DomainSelectionStatus(
                benchmark=benchmark,
                next_action=action,
                reasons=reasons,
            )
        if action in {"extend_replay_to_5", "rerun_candidate_1", "run_candidate_2"}:
            return DomainSelectionStatus(
                benchmark=benchmark,
                next_action=action,
                reasons=reasons,
            )
        if action == "run_candidate_3" and index < 3:
            if not _records_for(records, benchmark, 3):
                return DomainSelectionStatus(
                    benchmark=benchmark,
                    next_action="run_candidate_3",
                    reasons=reasons,
                )
            continue
        return DomainSelectionStatus(
            benchmark=benchmark,
            next_action="clean_blocked_after_three_candidates",
            reasons=reasons,
        )
    return DomainSelectionStatus(
        benchmark=benchmark,
        next_action="clean_blocked_after_three_candidates",
        reasons=["candidate_sequence_exhausted"],
    )


def _skilllearn_qualification_status(
    repository: SelectionRepository,
    records: list[CleanRunEvidence],
) -> DomainSelectionStatus:
    candidate = repository.candidates["skilllearnbench"][1]
    ready: list[str] = []
    reasons: list[str] = []
    for family in SKILLLEARN_FAMILIES:
        runs = _records_for(records, "skilllearnbench", 1, family)
        failures = _group_failures(candidate, runs, family=family)
        failures.extend(_selection_audit_failures(repository, candidate, runs))
        accepted = sum(
            run.accepted_update_count > 0
            and run.artifact_changed
            and run.validation_complete
            for run in runs
        )
        if not failures and accepted >= 2:
            ready.append(family)
        else:
            reasons.extend(f"{family}:{reason}" for reason in failures)
            if accepted < 2:
                reasons.append(f"{family}:fewer_than_two_accepted_updates")
    if len(ready) >= 3:
        return DomainSelectionStatus(
            benchmark="skilllearnbench",
            selected_candidate_index=1,
            next_action="freeze_candidate",
        )
    return DomainSelectionStatus(
        benchmark="skilllearnbench",
        next_action="clean_blocked_skilllearn_families",
        reasons=list(dict.fromkeys(reasons)),
    )


def _legacy_replay_sources(root: Path | None) -> list[dict[str, Any]]:
    """Record supplied historical replay evidence without treating it as new replay."""

    if root is None or not root.exists():
        return []
    sources: list[dict[str, Any]] = []
    for path in sorted(root.rglob("result.json")):
        try:
            replay = _read_object(path)
        except (OSError, ValueError):
            continue
        if replay.get("schema_version") != "rsebench.fixed-artifact-replay.v1":
            continue
        sources.append(
            {
                "path": str(path.resolve()),
                "benchmark": replay.get("benchmark"),
                "repeat_count": replay.get("repeat_count"),
                "task_ids": replay.get("task_ids"),
                "artifact_hashes": replay.get("artifact_hashes"),
                "integrity_failures": replay_integrity_failures(replay),
            }
        )
    return sources


def _reuse_audit(
    repository: SelectionRepository,
    run_root: Path,
    clean_v2_root: Path | None,
    skillopt_replay_root: Path | None,
) -> SelectionStatus:
    records = (
        discover_clean_runs(clean_v2_root, repository)
        if clean_v2_root is not None
        else []
    )
    source_payload = {
        "schema_version": "rsebench.reuse-audit-sources.v1",
        "runs": [record.model_dump(mode="json") for record in records],
        "legacy_replays": _legacy_replay_sources(skillopt_replay_root),
    }
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "reuse_audit_sources.json").write_text(
        json.dumps(source_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    domains: dict[str, DomainSelectionStatus] = {
        "spreadsheetbench_verified": DomainSelectionStatus(
            benchmark="spreadsheetbench_verified",
            next_action="run_candidate_2",
            reasons=["candidate_1_preregistered_failure"],
        ),
        "skilllearnbench": DomainSelectionStatus(
            benchmark="skilllearnbench",
            next_action="run_candidate_2",
            reasons=["fixed_family_qualification_required"],
        ),
    }
    for benchmark in ("officeqa_full", "webshop"):
        candidate = repository.candidates[benchmark][1]
        runs = _records_for(records, benchmark, 1)
        failures = _group_failures(candidate, runs, family=None)
        domains[benchmark] = DomainSelectionStatus(
            benchmark=benchmark,
            next_action=("rerun_candidate_1" if failures else "replay_candidate_1"),
            reasons=failures,
        )
    return SelectionStatus(domains=domains)


def _qualification(
    repository: SelectionRepository,
    run_root: Path,
) -> SelectionStatus:
    records = discover_clean_runs(run_root, repository)
    reuse_path = run_root / "reuse_audit_sources.json"
    if reuse_path.is_file():
        payload = _read_object(reuse_path)
        records = _overlay_reused_records(
            records,
            [
                CleanRunEvidence.model_validate(row)
                for row in payload.get("runs", [])
            ],
        )
    domains = {
        benchmark: _pool_qualification_status(
            repository, records, run_root, benchmark
        )
        for benchmark in POOL_BENCHMARKS
    }
    domains["skilllearnbench"] = _skilllearn_qualification_status(
        repository, records
    )
    return SelectionStatus(domains=domains)


def _screening(
    repository: SelectionRepository,
    run_root: Path,
) -> ScreeningGeneralizationAggregate:
    status = SelectionStatus.model_validate_json(
        (run_root / "selection_status.json").read_text(encoding="utf-8")
    )
    records = discover_clean_runs(run_root, repository)
    reuse_path = run_root / "reuse_audit_sources.json"
    if reuse_path.is_file():
        records = _overlay_reused_records(
            records,
            [
                CleanRunEvidence.model_validate(row)
                for row in _read_object(reuse_path).get("runs", [])
            ],
        )
    domains: dict[str, DomainScreeningGeneralization] = {}
    for benchmark in POOL_BENCHMARKS:
        selected = status.domains[benchmark].selected_candidate_index
        if selected is None:
            domains[benchmark] = DomainScreeningGeneralization(
                status="clean_generalization_failed",
                failure_reasons=["no_selected_candidate"],
            )
            continue
        candidate = repository.candidates[benchmark][selected]
        seeds: list[ScreeningSeedEvidence] = []
        selected_runs = _records_for(records, benchmark, selected)
        failures = [
            *_group_failures(candidate, selected_runs, family=None),
            *_selection_audit_failures(repository, candidate, selected_runs),
        ]
        for run in sorted(
            selected_runs, key=lambda item: item.method_seed
        ):
            replay, replay_failures = _load_replay(
                _replay_result_path(
                    run_root,
                    role="screening_test",
                    benchmark=benchmark,
                    candidate_index=selected,
                    method_seed=run.method_seed,
                    family=None,
                ),
                candidate=candidate,
                run=run,
                evaluation_role="screening_test",
            )
            failures.extend(replay_failures)
            if replay is not None and not replay_failures:
                seeds.append(
                    ScreeningSeedEvidence(
                        method_seed=run.method_seed,
                        mean_delta_vs_seed=float(
                            replay["summaries"]["clean"][
                                "mean_delta_vs_reference"
                            ]
                        ),
                        execution_complete=True,
                        replay_count=int(replay["repeat_count"]),
                    )
                )
        if failures or len(seeds) != 3:
            domains[benchmark] = DomainScreeningGeneralization(
                status="clean_generalization_failed",
                failure_reasons=list(dict.fromkeys(failures or ["missing_three_seeds"])),
            )
        else:
            decision = decide_screening_generalization(
                seeds=seeds, execution_coverage=1.0
            )
            domains[benchmark] = DomainScreeningGeneralization(
                status=decision.status,
                decision=decision,
                failure_reasons=decision.failure_reasons,
            )
    selected = status.domains["skilllearnbench"].selected_candidate_index
    family_decisions: dict[str, Any] = {}
    ready_families: list[str] = []
    skill_failures: list[str] = []
    if selected == 1:
        candidate = repository.candidates["skilllearnbench"][1]
        for family in SKILLLEARN_FAMILIES:
            seeds: list[ScreeningSeedEvidence] = []
            family_runs = _records_for(records, "skilllearnbench", 1, family)
            family_failures = [
                *_group_failures(candidate, family_runs, family=family),
                *_selection_audit_failures(repository, candidate, family_runs),
            ]
            skill_failures.extend(
                f"{family}:{reason}" for reason in family_failures
            )
            for run in sorted(
                family_runs,
                key=lambda item: item.method_seed,
            ):
                replay, replay_failures = _load_replay(
                    _replay_result_path(
                        run_root,
                        role="screening_test",
                        benchmark="skilllearnbench",
                        candidate_index=1,
                        method_seed=run.method_seed,
                        family=family,
                    ),
                    candidate=candidate,
                    run=run,
                    evaluation_role="screening_test",
                )
                skill_failures.extend(
                    f"{family}:{reason}" for reason in replay_failures
                )
                if replay is not None and not replay_failures:
                    seeds.append(
                        ScreeningSeedEvidence(
                            method_seed=run.method_seed,
                            mean_delta_vs_seed=float(
                                replay["summaries"]["clean"][
                                    "mean_delta_vs_reference"
                                ]
                            ),
                            execution_complete=True,
                            replay_count=int(replay["repeat_count"]),
                        )
                    )
            if len(seeds) == 3:
                decision = decide_screening_generalization(
                    seeds=seeds, execution_coverage=1.0
                )
                family_decisions[family] = decision
                if decision.status == "clean_generalization_ready":
                    ready_families.append(family)
    skill_ready = len(ready_families) >= 3
    domains["skilllearnbench"] = DomainScreeningGeneralization(
        status=(
            "clean_generalization_ready"
            if skill_ready
            else "clean_generalization_failed"
        ),
        ready_families=ready_families,
        family_decisions=family_decisions,
        failure_reasons=(
            []
            if skill_ready
            else list(dict.fromkeys(skill_failures or ["fewer_than_three_ready_families"]))
        ),
    )
    return ScreeningGeneralizationAggregate(
        domains=domains,
        all_ready=all(row.status == "clean_generalization_ready" for row in domains.values()),
    )


def aggregate_selection_roots(
    *,
    selection_root: Path,
    run_root: Path,
    mode: str,
    clean_v2_root: Path | None = None,
    skillopt_replay_root: Path | None = None,
) -> SelectionStatus | ScreeningGeneralizationAggregate:
    repository = load_selection_repository(selection_root)
    root = run_root.resolve()
    if mode == "reuse-audit":
        return _reuse_audit(
            repository,
            root,
            clean_v2_root,
            skillopt_replay_root,
        )
    if mode == "qualification":
        return _qualification(repository, root)
    if mode == "screening-generalization":
        return _screening(repository, root)
    raise ValueError(f"unknown aggregation mode: {mode}")


def _project_root() -> Path:
    root = Path(__file__).resolve().parents[3]
    if not (root / "pyproject.toml").is_file():
        raise ValueError("qualification module is not inside an RSEBench checkout")
    return root


def discover_replay_jobs(
    *,
    selection_root: Path,
    run_root: Path,
    evaluation_role: str,
    candidate_index: int | None,
    repeats: int,
    resume: bool,
) -> list[dict[str, Any]]:
    if repeats not in {3, 5}:
        raise ValueError("replay repeats must be exactly 3 or 5")
    if evaluation_role not in {"qualification_test", "screening_test"}:
        raise ValueError(f"unknown replay role: {evaluation_role}")
    repository = load_selection_repository(selection_root)
    records = discover_clean_runs(run_root, repository)
    reuse_path = run_root / "reuse_audit_sources.json"
    if reuse_path.is_file():
        records = _overlay_reused_records(
            records,
            [
                CleanRunEvidence.model_validate(row)
                for row in _read_object(reuse_path).get("runs", [])
            ],
        )
    selected: dict[str, int] = {}
    if evaluation_role == "screening_test":
        status = SelectionStatus.model_validate_json(
            (run_root / "selection_status.json").read_text(encoding="utf-8")
        )
        for benchmark, row in status.domains.items():
            if row.selected_candidate_index is not None:
                selected[benchmark] = row.selected_candidate_index
    project = _project_root()
    jobs: list[dict[str, Any]] = []
    for run in sorted(
        records,
        key=lambda row: (
            row.benchmark,
            row.candidate_index,
            row.family or "",
            row.method_seed,
        ),
    ):
        if run.failure_reasons:
            continue
        if candidate_index is not None and run.candidate_index != candidate_index:
            continue
        if evaluation_role == "qualification_test" and run.benchmark == "skilllearnbench":
            continue
        if evaluation_role == "screening_test" and selected.get(run.benchmark) != (
            run.candidate_index
        ):
            continue
        output = _replay_result_path(
            run_root,
            role=evaluation_role,
            benchmark=run.benchmark,
            candidate_index=run.candidate_index,
            method_seed=run.method_seed,
            family=run.family,
        ).parent
        existing = output / "result.json"
        adapter_resume = False
        if existing.is_file():
            existing_repeats = int(_read_object(existing).get("repeat_count", 0))
            if existing_repeats == repeats:
                continue
            if not (resume and existing_repeats == 3 and repeats == 5):
                raise ValueError("existing replay can only resume from 3 to 5")
            adapter_resume = True
        elif repeats == 5:
            raise ValueError("five-repeat replay requires an existing three-repeat result")
        manifest = repository.candidate_paths[(run.benchmark, run.candidate_index)]
        launcher = {
            "spreadsheetbench_verified": "scripts/replay_fixed_skillopt_artifacts.py",
            "officeqa_full": "scripts/replay_fixed_skillopt_artifacts.py",
            "webshop": "scripts/replay_fixed_skilladaptor_artifacts.py",
            "skilllearnbench": "scripts/replay_fixed_skilllearn_artifacts.py",
        }[run.benchmark]
        command = [
            sys.executable,
            str((project / launcher).resolve()),
            "--manifest",
            str(manifest),
            "--evaluation-role",
            evaluation_role,
            "--artifact",
            f"seed={run.seed_artifact_path}",
            "--artifact",
            f"clean={run.clean_artifact_path}",
            "--reference",
            "seed",
            "--repeats",
            str(repeats),
            "--output-dir",
            str(output),
        ]
        if adapter_resume:
            command.append("--resume")
        if run.family is not None:
            command.extend(
                [
                    "--family",
                    run.family,
                    "--image-manifest",
                    str(
                        project
                        / "outputs/preflight/noise-screen-v1/skilllearn_image_manifest.json"
                    ),
                ]
            )
        jobs.append(
            {
                "benchmark": run.benchmark,
                "candidate_index": run.candidate_index,
                "family": run.family,
                "method_seed": run.method_seed,
                "evaluation_role": evaluation_role,
                "output_dir": str(output),
                "command": command,
            }
        )
    return jobs


__all__ = [
    "CleanRunEvidence",
    "SelectionRepository",
    "aggregate_selection_roots",
    "discover_clean_runs",
    "discover_replay_jobs",
    "load_selection_repository",
    "read_clean_run",
    "validate_candidate_denominators",
]
