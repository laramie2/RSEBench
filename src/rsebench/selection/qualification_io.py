"""Filesystem-owned evidence discovery for stable split qualification."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.experiments.contracts import ExperimentIdentity
from rsebench.experiments.preflight import (
    _default_fingerprint_resolver,
    _methods_root,
    _resolve_path,
    load_experiment_matrix,
)
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
    audit_officeqa,
    audit_skilllearn,
    audit_spreadsheet,
    audit_webshop,
    candidate_failure_action,
    decide_candidate,
    decide_screening_generalization,
    replay_action,
    replay_integrity_failures,
    reuse_identity_failures,
    screening_family_ready,
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


def normalized_evolution_input_hash(
    *,
    candidate: StableSplitCandidate,
    family: str | None,
    runtime: dict[str, Any],
    seed_skill_hash: str,
    provider: str,
    model: str,
    train_tasks: list[TaskManifest] | None = None,
    validation_tasks: list[TaskManifest] | None = None,
) -> str:
    """Hash current evolution inputs without path/commit/manifest-file coupling."""

    if (train_tasks is None) != (validation_tasks is None):
        raise ValueError("train and validation task overrides must be supplied together")
    if train_tasks is not None and validation_tasks is not None:
        train = train_tasks
        validation = validation_tasks
    elif family:
        allocation = candidate.metadata["static_audit"]["family_allocations"][family]
        train_ids = set(allocation["train"])
        validation_ids = set(allocation["validation"])
        train = [task for task in candidate.train if task.task_id in train_ids]
        validation = [
            task for task in candidate.validation if task.task_id in validation_ids
        ]
    else:
        train = candidate.train
        validation = candidate.validation
    return canonical_hash(
        {
            "benchmark": candidate.benchmark,
            "candidate_index": candidate.candidate_index,
            "selection_hash": candidate.selection_hash,
            "family": family,
            "train": [
                {
                    "task_id": task.task_id,
                    "benchmark": task.benchmark,
                    "domain": task.domain,
                    "prompt": task.prompt,
                    "gold_answers": list(task.gold_answers),
                    "source_hash": task.source_hash,
                    "verifier": task.verifier,
                }
                for task in train
            ],
            "validation": [
                {
                    "task_id": task.task_id,
                    "benchmark": task.benchmark,
                    "domain": task.domain,
                    "prompt": task.prompt,
                    "gold_answers": list(task.gold_answers),
                    "source_hash": task.source_hash,
                    "verifier": task.verifier,
                }
                for task in validation
            ],
            "runtime": runtime,
            "seed_skill_hash": seed_skill_hash,
            "provider": provider,
            "model": model,
            "stage": "clean",
        }
    )


def _current_candidate_one_identities(
    repository: SelectionRepository,
) -> dict[tuple[str, int], dict[str, Any]]:
    """Resolve Candidate-1 identity from the current fallback configuration."""

    project = _project_root()
    matrix = load_experiment_matrix(
        project / "configs/experiments/noise-screen-v1-reuse-fallback.yaml"
    )
    provider_config_hash = sha256_file(project / matrix.provider_config)
    resolve_fingerprint = _default_fingerprint_resolver(project)
    methods_root = _methods_root(project)
    expected: dict[tuple[str, int], dict[str, Any]] = {}
    for cell in matrix.cells:
        candidate = repository.candidates[cell.benchmark][1]
        seed_hash = sha256_file(
            _resolve_path(project, methods_root, cell.seed_skill)
        )
        runtime = {
            **cell.runtime,
            "temperature": matrix.temperature,
            "thinking": matrix.thinking,
            "provider_config_hash": provider_config_hash,
        }
        if cell.family is not None:
            runtime["family"] = cell.family
        fingerprint = resolve_fingerprint(cell.baseline).fingerprint
        evolution_hash = normalized_evolution_input_hash(
            candidate=candidate,
            family=cell.family,
            runtime=runtime,
            seed_skill_hash=seed_hash,
            provider=matrix.provider,
            model=matrix.model,
        )
        for seed in matrix.method_seeds:
            expected[(cell.benchmark, seed)] = {
                "baseline_fingerprint": fingerprint,
                "evolution_input_hash": evolution_hash,
                "provider": matrix.provider,
                "model": matrix.model,
                "provider_config_hash": provider_config_hash,
                "method_seed": seed,
                "seed_artifact_hash": seed_hash,
            }
    return expected


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"expected JSON object line: {path}")
        rows.append(payload)
    return rows


def _provenance(run_dir: Path, paths: list[Path]) -> dict[str, Any]:
    files = [
        {
            "path": str(path.resolve().relative_to(run_dir.resolve())),
            "sha256": sha256_file(path),
        }
        for path in sorted(set(paths))
        if path.is_file()
    ]
    return {
        "evidence_source": "owned_persisted_outputs",
        "evidence_files": files,
        "evidence_hash": canonical_hash(files),
    }


def _missing_owned_audits(
    run_dir: Path, reason: str, paths: list[Path]
) -> tuple[dict[str, Any], dict[str, Any]]:
    provenance = _provenance(run_dir, paths)
    return (
        {
            "N3": {"status": "missing", "coverage": 0.0, **provenance},
            "N4": {"status": "missing", "coverage": 0.0, **provenance},
        },
        {
            "passed": False,
            "execution_coverage": 0.0,
            "evidence_complete": False,
            "failure_reasons": [reason],
            **provenance,
        },
    )


def _skillopt_owned_audits(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
) -> tuple[dict[str, Any], dict[str, Any]]:
    native = run_dir / "clean/native_train"
    rollout_paths = sorted(native.glob("steps/step_*/rollout/results.jsonl"))
    summary_path = native / "summary.json"
    evidence_paths = [*rollout_paths, summary_path]
    if len(rollout_paths) != 3 or not summary_path.is_file():
        return _missing_owned_audits(
            run_dir, "missing_owned_skillopt_trace", evidence_paths
        )
    try:
        batches = [_read_jsonl(path) for path in rollout_paths]
        summary = _read_object(summary_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return _missing_owned_audits(
            run_dir, "unreadable_owned_skillopt_trace", evidence_paths
        )
    expected_ids = _ids(candidate.train)
    actual_ids = [str(row.get("id") or "") for batch in batches for row in batch]
    exact_tasks = _same_unique_ids(actual_ids, expected_ids)
    outcomes = [[bool(row.get("hard")) for row in batch] for batch in batches]
    n3_ids: set[str] = set()
    n4_ids: set[str] = set()
    patch_coverage = True
    for rollout_path, batch in zip(rollout_paths, batches, strict=True):
        step = rollout_path.parent.parent
        for row in batch:
            task_id = str(row.get("id") or "")
            conversation_path = step / "rollout/predictions" / task_id / "conversation.json"
            evidence_paths.append(conversation_path)
            if not conversation_path.is_file():
                continue
            conversation = json.loads(conversation_path.read_text(encoding="utf-8"))
            if not isinstance(conversation, list):
                continue
            if candidate.benchmark == "spreadsheetbench_verified":
                assistant = "\n".join(
                    str(item.get("content") or "")
                    for item in conversation
                    if isinstance(item, dict) and item.get("role") == "assistant"
                )
                if "load_workbook" in assistant and ".save(" in assistant:
                    n3_ids.add(task_id)
                attribution = str(row.get("target_user_prompt") or "")
                if (
                    "Expected answer position:" in attribution
                    and "load_workbook" in assistant
                    and any(token in assistant for token in ("wb[", ".cell(", "iter_rows"))
                ):
                    n4_ids.add(task_id)
            else:
                tool_rows = [
                    item
                    for item in conversation
                    if isinstance(item, dict) and item.get("type") == "tool_call"
                ]
                if any(
                    str(item.get("cmd") or "").startswith(("grep(", "read("))
                    and bool(str(item.get("obs") or "").strip())
                    for item in tool_rows
                ):
                    n3_ids.add(task_id)
                    n4_ids.add(task_id)
        patch_paths = sorted((step / "patches").glob("minibatch_*.json"))
        evidence_paths.extend(patch_paths)
        patch_counts = {"success": 0, "failure": 0}
        for path in patch_paths:
            patch = _read_object(path)
            source_type = str(patch.get("source_type") or "")
            body = patch.get("patch")
            if source_type not in patch_counts or not isinstance(body, dict) or not body:
                patch_coverage = False
                continue
            patch_counts[source_type] += int(patch.get("batch_size", 0))
        successes = sum(bool(row.get("hard")) for row in batch)
        if patch_counts != {"success": successes, "failure": len(batch) - successes}:
            patch_coverage = False
    n3_coverage = len(n3_ids & set(expected_ids)) / len(expected_ids)
    n4_coverage = len(n4_ids & set(expected_ids)) / len(expected_ids)
    provenance = _provenance(run_dir, evidence_paths)
    trace = {
        "N3": {
            "status": "pass" if exact_tasks and n3_coverage == 1.0 else "fail",
            "coverage": n3_coverage,
            **provenance,
        },
        "N4": {
            "status": (
                "pass"
                if exact_tasks and patch_coverage and n4_coverage == 1.0
                else "fail"
            ),
            "coverage": n4_coverage if patch_coverage else 0.0,
            **provenance,
        },
    }
    validation_score = float(summary.get("baseline_selection_hard", -1.0))
    if candidate.benchmark == "spreadsheetbench_verified":
        audit = audit_spreadsheet(
            validation_score=validation_score,
            train_batches=outcomes,
        )
    else:
        parseable = sum(
            bool(str(row.get("predicted_answer") or "").strip())
            for batch in batches
            for row in batch
        ) / len(expected_ids)
        audit = audit_officeqa(
            validation_score=validation_score,
            parseable_answer_rate=parseable,
            train_batches=outcomes,
        )
    domain = {
        **audit.model_dump(mode="json"),
        "evidence_complete": True,
        **provenance,
    }
    if not exact_tasks:
        domain["passed"] = False
        domain["failure_reasons"].append("owned_train_task_set_differs")
    return trace, domain


def _webshop_owned_audits(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
    runtime: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    retrieval_path = run_dir / "clean/retrieval_audit/clean_evolution.jsonl"
    fault_path = run_dir / "clean/native_train/reasoning_faults.log"
    manifest_path = run_dir / "clean/webshop_task_manifest.json"
    evidence_paths = [retrieval_path, fault_path, manifest_path]
    if not all(path.is_file() for path in evidence_paths):
        return _missing_owned_audits(
            run_dir, "missing_owned_webshop_trace", evidence_paths
        )
    try:
        retrieval = _read_jsonl(retrieval_path)
        manifest = _read_object(manifest_path)
        fault_text = fault_path.read_text(encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError):
        return _missing_owned_audits(
            run_dir, "unreadable_owned_webshop_trace", evidence_paths
        )
    expected_ids = _ids(candidate.train)
    manifest_ids = [f"goal_{value}" for value in manifest.get("input_tasks", [])]
    exact_tasks = manifest_ids == expected_ids
    events: dict[str, set[str]] = {task_id: set() for task_id in expected_ids}
    for row in retrieval:
        task_id = str(row.get("episode_id") or "")
        if task_id in events:
            events[task_id].add(str(row.get("event") or ""))
    n3_ids = {
        task_id
        for task_id, kinds in events.items()
        if {"retrieval", "prompt_injection"}.issubset(kinds)
    }
    fault_ids = set(
        re.findall(r"Task:\s*(goal_\d+)\s*\|\s*Step:\s*\d+\s*\|\s*Obs:", fault_text)
    )
    n3_coverage = len(n3_ids) / len(expected_ids)
    n4_coverage = len(fault_ids & set(expected_ids)) / len(expected_ids)
    provenance = _provenance(run_dir, evidence_paths)
    trace = {
        "N3": {
            "status": "pass" if exact_tasks and n3_coverage == 1.0 else "fail",
            "coverage": n3_coverage,
            **provenance,
        },
        "N4": {
            "status": "pass" if exact_tasks and n4_coverage == 1.0 else "fail",
            "coverage": n4_coverage,
            **provenance,
        },
    }
    all_tasks = [
        *candidate.train,
        *candidate.validation,
        *candidate.qualification_test,
    ]
    audit = audit_webshop(
        target_reachable=[task.metadata.get("target_reachable") is True for task in all_tasks],
        validation_outcomes=[
            task.metadata.get("seed_success") is True for task in candidate.validation
        ],
        max_episode_steps=int(runtime.get("max_episode_steps", 0)),
    )
    domain = {
        **audit.model_dump(mode="json"),
        "evidence_complete": True,
        **provenance,
    }
    if not exact_tasks:
        domain["passed"] = False
        domain["failure_reasons"].append("owned_train_task_set_differs")
    return trace, domain


def _skilllearn_owned_audits(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
    family: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    allocation = candidate.metadata["static_audit"]["family_allocations"][family]
    train_ids = list(allocation["train"])
    validation_ids = list(allocation["validation"])
    evolution_root = run_dir / "clean/evolution"
    round_dirs = sorted(path for path in evolution_root.glob("round-*") if path.is_dir())
    by_task = {path.name.split("-", maxsplit=2)[-1]: path for path in round_dirs}
    evidence_paths: list[Path] = []
    n3_ids: set[str] = set()
    n4_ids: set[str] = set()
    executions: list[dict[str, Any]] = []
    leak_markers = ("/tests/", "test_outputs.py::", "ctrf.json", "reference_solution")
    for task_id in train_ids:
        task_dir = by_task.get(task_id)
        if task_dir is None:
            continue
        trajectory_path = task_dir / "visible_trajectory.json"
        feedback_path = task_dir / "visible_feedback.json"
        image_path = task_dir / "execution/image/image_record.json"
        verifier_path = task_dir / "execution/verifier/ctrf.json"
        evidence_paths.extend(
            [trajectory_path, feedback_path, image_path, verifier_path]
        )
        if not all(path.is_file() for path in evidence_paths[-4:]):
            continue
        trajectory = _read_object(trajectory_path)
        feedback = _read_object(feedback_path)
        visible = json.dumps([trajectory, feedback], ensure_ascii=False).casefold()
        if (
            trajectory.get("task_id") == task_id
            and isinstance(trajectory.get("events"), list)
            and trajectory["events"]
        ):
            n3_ids.add(task_id)
        blamed = feedback.get("blamed_event_ids")
        if (
            feedback.get("task_id") == task_id
            and isinstance(blamed, list)
            and blamed
            and bool(str(feedback.get("recommendation") or "").strip())
        ):
            n4_ids.add(task_id)
        executions.append(
            {
                "container_started": bool(_read_object(image_path).get("image_id")),
                "verifier_completed": isinstance(
                    _read_object(verifier_path).get("results"), dict
                ),
                "hidden_test_exposed": any(marker in visible for marker in leak_markers),
            }
        )
    if validation_ids:
        validation_dir = run_dir / "clean/validation/round-2" / validation_ids[0]
        image_path = validation_dir / "image/image_record.json"
        verifier_path = validation_dir / "verifier/ctrf.json"
        evidence_paths.extend([image_path, verifier_path])
        if image_path.is_file() and verifier_path.is_file():
            executions.append(
                {
                    "container_started": bool(_read_object(image_path).get("image_id")),
                    "verifier_completed": isinstance(
                        _read_object(verifier_path).get("results"), dict
                    ),
                    "hidden_test_exposed": False,
                }
            )
    if len(round_dirs) < len(train_ids):
        return _missing_owned_audits(
            run_dir, "missing_owned_skilllearn_trace", evidence_paths
        )
    n3_coverage = len(n3_ids) / len(train_ids)
    n4_coverage = len(n4_ids) / len(train_ids)
    provenance = _provenance(run_dir, evidence_paths)
    trace = {
        "N3": {
            "status": "pass" if n3_coverage == 1.0 else "fail",
            "coverage": n3_coverage,
            **provenance,
        },
        "N4": {
            "status": "pass" if n4_coverage == 1.0 else "fail",
            "coverage": n4_coverage,
            **provenance,
        },
    }
    audit = audit_skilllearn(executions=executions)
    return trace, {
        **audit.model_dump(mode="json"),
        "evidence_complete": len(executions) == 3,
        **provenance,
    }


def derive_owned_run_audits(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
    family: str | None,
    runtime: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive N3/N4 and domain gates only from baseline-owned persisted outputs."""

    if candidate.benchmark in {"spreadsheetbench_verified", "officeqa_full"}:
        return _skillopt_owned_audits(run_dir, candidate=candidate)
    if candidate.benchmark == "webshop":
        return _webshop_owned_audits(
            run_dir, candidate=candidate, runtime=runtime
        )
    if candidate.benchmark == "skilllearnbench" and family:
        return _skilllearn_owned_audits(
            run_dir, candidate=candidate, family=family
        )
    return _missing_owned_audits(run_dir, "unsupported_owned_trace_contract", [])


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
    evolution_input_hash = normalized_evolution_input_hash(
        candidate=candidate,
        family=family,
        runtime=inputs["runtime"],
        seed_skill_hash=seed_hash,
        provider=identity.inputs.provider,
        model=identity.inputs.model,
        train_tasks=[TaskManifest.model_validate(row) for row in split["train"]],
        validation_tasks=[
            TaskManifest.model_validate(row) for row in split["validation"]
        ],
    )
    trace_applicability, domain_audit = derive_owned_run_audits(
        run_dir,
        candidate=candidate,
        family=family,
        runtime=inputs["runtime"],
    )
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
        evolution_input_hash=evolution_input_hash,
        provider=identity.inputs.provider,
        model=identity.inputs.model,
        provider_config_hash=provider_config_hash,
        trace_applicability=trace_applicability,
        domain_audit=domain_audit,
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


def _selection_audit_failure_groups(
    repository: SelectionRepository,
    candidate: StableSplitCandidate,
    runs: list[CleanRunEvidence],
) -> tuple[list[str], list[str]]:
    """Require static, trace-derived, and domain gates from owned evidence."""

    retryable: list[str] = []
    deterministic: list[str] = []
    static_rows = _applicability_rows(
        repository.audits[(candidate.benchmark, candidate.candidate_index)]
    )
    for stage in ("N1", "N2"):
        row = static_rows.get(stage)
        if not isinstance(row, dict):
            deterministic.append(f"missing_noise_applicability:{stage}")
        elif row.get("status") != "pass" or row.get("coverage") != 1.0:
            deterministic.append(f"incomplete_noise_applicability:{stage}")
    for run in runs:
        for stage in ("N3", "N4"):
            row = run.trace_applicability.get(stage)
            if not isinstance(row, dict):
                retryable.append(f"missing_noise_applicability:{stage}")
            elif row.get("status") in {"pending", "missing"}:
                retryable.append(f"missing_noise_applicability:{stage}")
            elif row.get("status") != "pass" or row.get("coverage") != 1.0:
                deterministic.append(f"incomplete_noise_applicability:{stage}")
        if not run.domain_audit:
            retryable.append("missing_domain_audit")
        elif run.domain_audit.get("evidence_complete") is not True:
            reasons = run.domain_audit.get("failure_reasons")
            if isinstance(reasons, list) and reasons:
                retryable.extend(str(reason) for reason in reasons)
            else:
                retryable.append("missing_domain_audit")
        elif run.domain_audit.get("passed") is not True:
            reasons = run.domain_audit.get("failure_reasons")
            if isinstance(reasons, list) and reasons:
                deterministic.extend(str(reason) for reason in reasons)
            else:
                deterministic.append("domain_structural_audit_failed")
    return list(dict.fromkeys(retryable)), list(dict.fromkeys(deterministic))


def _selection_audit_failures(
    repository: SelectionRepository,
    candidate: StableSplitCandidate,
    runs: list[CleanRunEvidence],
) -> list[str]:
    retryable, deterministic = _selection_audit_failure_groups(
        repository, candidate, runs
    )
    return [*retryable, *deterministic]


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
    group_failures = _group_failures(candidate, runs, family=family)
    retryable_audit, deterministic_audit = _selection_audit_failure_groups(
        repository, candidate, runs
    )
    if group_failures or retryable_audit:
        return sequential_incomplete_action(candidate.candidate_index), [
            *group_failures,
            *retryable_audit,
        ]
    if deterministic_audit:
        return candidate_failure_action(
            candidate.candidate_index, deterministic=True
        ), deterministic_audit
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
                "reuse_disposition": "replay_required",
                "reuse_reasons": ["legacy_replay_not_canonical_per_seed"],
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
    expected_identities = _current_candidate_one_identities(repository)
    identity_audits: list[dict[str, Any]] = []
    current_failures: dict[str, list[str]] = {}
    for run in records:
        expected = expected_identities.get((run.benchmark, run.method_seed))
        if expected is None:
            continue
        expected = {**expected, "artifact_hash": run.clean_artifact_hash}
        actual = {
            "baseline_fingerprint": run.baseline_fingerprint,
            "evolution_input_hash": run.evolution_input_hash,
            "provider": run.provider,
            "model": run.model,
            "provider_config_hash": run.provider_config_hash,
            "method_seed": run.method_seed,
            "artifact_hash": run.clean_artifact_hash,
        }
        failures = reuse_identity_failures(actual, expected)
        if run.seed_artifact_hash != expected["seed_artifact_hash"]:
            failures.append("reuse_identity_mismatch:seed_artifact_hash")
        key = f"{run.benchmark}:{run.method_seed}"
        current_failures[key] = failures
        identity_audits.append(
            {
                "benchmark": run.benchmark,
                "method_seed": run.method_seed,
                "actual": actual,
                "expected": expected,
                "failure_reasons": failures,
            }
        )
    source_payload = {
        "schema_version": "rsebench.reuse-audit-sources.v1",
        "runs": [record.model_dump(mode="json") for record in records],
        "legacy_replays": _legacy_replay_sources(skillopt_replay_root),
        "current_identity_audits": identity_audits,
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
        for run in runs:
            failures.extend(
                current_failures.get(f"{benchmark}:{run.method_seed}", [])
            )
        failures = list(dict.fromkeys(failures))
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
            family_replay_failures: list[str] = []
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
                family_replay_failures.extend(replay_failures)
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
                if screening_family_ready(
                    decision,
                    evidence_failures=[
                        *family_failures,
                        *family_replay_failures,
                    ],
                ):
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
    "derive_owned_run_audits",
    "load_selection_repository",
    "normalized_evolution_input_hash",
    "read_clean_run",
    "validate_candidate_denominators",
]
