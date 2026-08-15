"""Filesystem-owned evidence discovery for stable split qualification."""

from __future__ import annotations

import json
import math
import os
import random
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.core1.dataset import _portable_reference
from rsebench.evidence import (
    FeedbackRecord,
    HookContext,
    RuntimeNoiseSpec,
    TrajectoryRecord,
    canonical_hash,
    mutate_record,
)
from rsebench.evolution.skilladaptor_executor import (
    SkillAdaptorOwnedFeedback,
    SkillAdaptorOwnedTrajectory,
)
from rsebench.evolution.skilllearn_executor import SkillLearnImageRecord
from rsebench.evolution.skillopt_evidence import (
    SkillOptEvidenceAdapter,
    _enrich_n3_spec,
    _enrich_n4_spec,
)
from rsebench.experiments.contracts import ExperimentIdentity
from rsebench.experiments.preflight import (
    _default_fingerprint_resolver,
    _methods_root,
    _resolve_path,
    load_experiment_matrix,
)
from rsebench.hashing import sha256_file
from rsebench.selection.contracts import (
    CandidateDecision,
    CandidateSeedEvidence,
    DomainSelectionStatus,
    PoolCandidateDecision,
    ScreeningSeedEvidence,
    SelectionStatus,
    SkillLearnFamilyQualificationSummary,
    SkillLearnQualificationDecision,
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


class ReuseRunIndex(StrictModel):
    """Hash-bound provenance index; deliberately contains no run evidence."""

    schema_version: Literal["rsebench.reuse-run-index.v1"]
    source_root: str
    source_root_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_dirs: list[str]
    index_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SkillOptRolloutRow(BaseModel):
    """Strict gate fields over a baseline row while preserving native extras."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    hard: bool | Literal[0, 1]
    soft: float
    predicted_answer: str | None = None
    fail_reason: str | None = None
    target_user_prompt: str | None = None
    source_files: list[str] = Field(default_factory=list)
    gold_document_ids: list[str] = Field(default_factory=list)

    @field_validator("hard", mode="before")
    @classmethod
    def strict_hard(cls, value: Any) -> Any:
        if isinstance(value, bool) or type(value) is int and value in {0, 1}:
            return value
        raise ValueError("hard must be a boolean or integer 0/1")

    @field_validator("soft", mode="before")
    @classmethod
    def finite_soft(cls, value: Any) -> Any:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("soft must be finite")
        return value


class SkillOptConversationItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str | None = None
    role: str | None = None
    content: str | None = None
    cmd: str | None = None
    obs: str | None = None
    action: str | None = None
    env_feedback: str | None = None


class SkillLearnVerifierSummary(StrictModel):
    tests: StrictInt = Field(ge=1)
    passed: StrictInt = Field(ge=0)
    failed: StrictInt = Field(ge=0)
    skipped: StrictInt = Field(ge=0)
    pending: StrictInt = Field(ge=0)
    other: StrictInt = Field(ge=0)
    start: float | None = None
    stop: float | None = None

    @field_validator("start", "stop", mode="before")
    @classmethod
    def finite_clock(cls, value: Any) -> Any:
        if value is None:
            return value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            raise ValueError("verifier clock must be finite and nonnegative")
        return value


class SkillLearnVerifierTest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: StrictStr = Field(min_length=1)
    status: Literal["passed", "failed", "skipped", "pending", "other"]
    duration: float | None = None

    @field_validator("duration", mode="before")
    @classmethod
    def finite_duration(cls, value: Any) -> Any:
        if value is None:
            return value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            raise ValueError("verifier duration must be finite and nonnegative")
        return value


class SkillLearnVerifierResults(StrictModel):
    tool: dict[str, Any]
    summary: SkillLearnVerifierSummary
    tests: list[SkillLearnVerifierTest] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_summary(self) -> "SkillLearnVerifierResults":
        if not self.tool:
            raise ValueError("verifier tool metadata must be nonempty")
        counts = {
            status: sum(row.status == status for row in self.tests)
            for status in ("passed", "failed", "skipped", "pending", "other")
        }
        if self.summary.tests != len(self.tests) or any(
            getattr(self.summary, status) != count
            for status, count in counts.items()
        ):
            raise ValueError("verifier summary differs from test records")
        return self


class SkillLearnVerifierRecord(StrictModel):
    results: SkillLearnVerifierResults


def _portable_task_identity(task: TaskManifest) -> dict[str, Any]:
    """Normalize declared root paths while retaining every TaskManifest field."""

    project = _project_root()
    roots = {
        "rsebench-project": project,
        "rsebench-data": Path(
            os.environ.get("RSEBENCH_DATA_ROOT", project / "data")
        ).resolve(),
        "rsebench-methods": _methods_root(project),
    }
    payload = task.model_dump(mode="json")
    payload["artifact_path"] = _portable_reference(
        payload.get("artifact_path"), roots
    )
    payload["metadata"] = _portable_reference(payload["metadata"], roots)
    return payload


_LEGACY_REUSE_PROJECTION_VERSION = "clean-v2-derived-annotations-v1"
_LEGACY_REUSE_METADATA_ALLOWLIST = {
    "officeqa_full": frozenset(
        {
            "officeqa_stratum",
            "static_applicability",
        }
    ),
    "webshop": frozenset(
        {
            "constraint_count",
            "normalized_query",
            "option_count",
            "retrieval_rank",
            "seed_success",
            "static_applicability",
            "target_reachable",
        }
    ),
}


def _legacy_reuse_task_identity(task: TaskManifest) -> dict[str, Any]:
    """Remove only clean-v2-absent annotations verified by pinned gates below."""

    allowlist = _LEGACY_REUSE_METADATA_ALLOWLIST.get(task.benchmark)
    if allowlist is None:
        raise ValueError("legacy reuse projection is not defined for benchmark")
    payload = _portable_task_identity(task)
    metadata = dict(payload["metadata"])
    for key in allowlist:
        metadata.pop(key, None)
    payload["metadata"] = metadata
    return payload


def _legacy_static_audit(candidate: StableSplitCandidate) -> Mapping[str, Any]:
    audit = candidate.metadata.get("static_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("legacy reuse current candidate lacks static audit")
    applicability = audit.get("noise_applicability")
    if not isinstance(applicability, Mapping) or any(
        applicability.get(stage) != {"coverage": 1.0, "status": "pass"}
        for stage in ("N1", "N2")
    ):
        raise ValueError("legacy reuse current candidate static audit is not passed")
    ordered = audit.get("ordered_task_ids")
    if not isinstance(ordered, Mapping) or ordered.get("train") != _ids(candidate.train) or (
        ordered.get("validation") != _ids(candidate.validation)
    ):
        raise ValueError("legacy reuse current candidate ordered audit differs")
    return audit


def _validate_officeqa_legacy_annotations(candidate: StableSplitCandidate) -> None:
    audit = _legacy_static_audit(candidate)
    gates = audit.get("coverage_gates")
    if not isinstance(gates, Mapping) or any(
        not isinstance(row, Mapping) or row.get("status") != "pass"
        for row in gates.values()
    ):
        raise ValueError("OfficeQA legacy reuse static coverage gate is not passed")
    if audit.get("train_batch_sizes") != [4, 4, 4]:
        raise ValueError("OfficeQA legacy reuse batch audit differs")
    for task in [*candidate.train, *candidate.validation]:
        metadata = task.metadata
        source_ids = metadata.get("gold_document_ids")
        source_count = metadata.get("source_file_count")
        difficulty = metadata.get("difficulty")
        if (
            not isinstance(source_ids, Sequence)
            or isinstance(source_ids, (str, bytes))
            or type(source_count) is not int
            or source_count != len(source_ids)
            or not isinstance(difficulty, str)
        ):
            raise ValueError("OfficeQA legacy reuse core source metadata is malformed")
        expected = {
            "officeqa_stratum": (
                f"difficulty={difficulty.casefold()}|files={source_count}"
            ),
            "static_applicability": {"N1": True, "N2": bool(source_ids)},
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("OfficeQA legacy reuse derived annotation differs")


def _validate_webshop_legacy_annotations(candidate: StableSplitCandidate) -> None:
    audit = _legacy_static_audit(candidate)
    if (
        audit.get("unique_normalized_queries") is not True
        or audit.get("reachable_target_asins") is not True
        or audit.get("validation_headroom") != {"successes": 2, "total": 5}
        or audit.get("train_batch_sizes") != [5]
    ):
        raise ValueError("WebShop legacy reuse static audit differs")
    project = _project_root()
    goals_payload = _read_object(
        project / "benchmark/validation/clean_qualification_v1/webshop_source.json"
    )
    selection = _read_object(
        project
        / "benchmark/validation/clean_qualification_v1/"
        "webshop_validation_selection.json"
    )
    products_path = _methods_root(project) / "webshop/data/items_shuffle_1000.json"
    products = json.loads(products_path.read_text(encoding="utf-8"))
    goals = goals_payload.get("goals")
    scores = selection.get("candidate_seed_scores")
    if (
        not isinstance(products, list)
        or not isinstance(goals, dict)
        or not isinstance(scores, dict)
    ):
        raise ValueError("WebShop legacy reuse pinned resources are malformed")
    seen_asins: set[str] = set()
    query_groups: dict[str, list[str]] = {}
    for product in products[:1000]:
        if not isinstance(product, dict):
            raise ValueError("WebShop legacy reuse product row is malformed")
        asin = product.get("asin")
        if (
            not isinstance(asin, str)
            or not asin
            or asin == "nan"
            or len(asin) > 10
            or asin in seen_asins
        ):
            continue
        seen_asins.add(asin)
        query = _normalized_webshop_query(product.get("query"))
        query_groups.setdefault(query, []).append(asin)
    role_tasks = {
        "train": candidate.train,
        "validation": candidate.validation,
        "qualification_test": candidate.qualification_test,
    }
    for role, tasks in role_tasks.items():
        for task in tasks:
            metadata = task.metadata
            raw_index = task.task_id.removeprefix("goal_")
            goal = goals.get(raw_index)
            if not isinstance(goal, dict):
                raise ValueError("WebShop legacy reuse pinned goal is missing")
            target = goal.get("asin")
            query = _normalized_webshop_query(goal.get("query"))
            attributes = goal.get("attributes")
            options = goal.get("goal_options")
            if (
                not isinstance(target, str)
                or not isinstance(attributes, list)
                or not isinstance(options, dict)
            ):
                raise ValueError("WebShop legacy reuse pinned goal is malformed")
            if (
                metadata.get("goal_idx") != int(raw_index)
                or metadata.get("target_asin") != target
                or metadata.get("query") != goal.get("query")
                or task.prompt != goal.get("instruction_text")
            ):
                raise ValueError("WebShop legacy reuse pinned core task differs")
            group = query_groups.get(query, [])
            rank = group.index(target) if target in group else 10_000
            constraint_count = len(attributes) + len(options) + 1
            expected = {
                "normalized_query": query,
                "target_reachable": rank < 10,
                "option_count": len(options),
                "constraint_count": constraint_count,
                "retrieval_rank": rank,
                "static_applicability": {
                    "N1": constraint_count >= 2,
                    "N2": rank < 10,
                },
            }
            if any(metadata.get(key) != value for key, value in expected.items()):
                raise ValueError("WebShop legacy reuse derived annotation differs")
            raw_score = scores.get(raw_index)
            if role == "validation":
                if (
                    isinstance(raw_score, bool)
                    or not isinstance(raw_score, (int, float))
                    or metadata.get("seed_success") != (float(raw_score) == 1.0)
                ):
                    raise ValueError("WebShop legacy reuse derived annotation differs")
            elif "seed_success" in metadata:
                raise ValueError("WebShop seed_success is only valid on validation tasks")


def _validate_legacy_reuse_candidate(candidate: StableSplitCandidate) -> None:
    if candidate.candidate_index != 1:
        raise ValueError("legacy reuse is restricted to Candidate 1")
    if candidate.benchmark == "officeqa_full":
        _validate_officeqa_legacy_annotations(candidate)
        return
    if candidate.benchmark == "webshop":
        _validate_webshop_legacy_annotations(candidate)
        return
    raise ValueError("legacy reuse is restricted to OfficeQA and WebShop")


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
    legacy_reuse: bool = False,
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
    if legacy_reuse:
        _validate_legacy_reuse_candidate(candidate)
    task_identity = (
        _legacy_reuse_task_identity if legacy_reuse else _portable_task_identity
    )
    return canonical_hash(
        {
            "benchmark": candidate.benchmark,
            "candidate_index": candidate.candidate_index,
            "selection_hash": candidate.selection_hash,
            "family": family,
            "train": [task_identity(task) for task in train],
            "validation": [task_identity(task) for task in validation],
            "runtime": runtime,
            "seed_skill_hash": seed_skill_hash,
            "provider": provider,
            "model": model,
            "stage": "clean",
            **(
                {"legacy_reuse_projection": _LEGACY_REUSE_PROJECTION_VERSION}
                if legacy_reuse
                else {}
            ),
        }
    )


def _current_candidate_one_identities(
    repository: SelectionRepository,
) -> dict[tuple[str, int, str | None], dict[str, Any]]:
    """Resolve Candidate-1 identity from the current fallback configuration."""

    project = _project_root()
    matrix = load_experiment_matrix(
        project / "configs/experiments/noise-screen-v1-reuse-fallback.yaml"
    )
    provider_config_hash = sha256_file(project / matrix.provider_config)
    resolve_fingerprint = _default_fingerprint_resolver(project)
    methods_root = _methods_root(project)
    expected: dict[tuple[str, int, str | None], dict[str, Any]] = {}
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
            legacy_reuse=cell.benchmark in _LEGACY_REUSE_METADATA_ALLOWLIST,
        )
        for seed in matrix.method_seeds:
            expected[(cell.benchmark, seed, cell.family)] = {
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
    def locator(path: Path) -> str:
        resolved = path.resolve()
        try:
            return str(resolved.relative_to(run_dir.resolve()))
        except ValueError:
            project = _project_root()
            try:
                return f"rsebench-project://{resolved.relative_to(project).as_posix()}"
            except ValueError:
                return f"external-sha256://{canonical_hash(str(resolved))}"

    files = [
        {
            "path": locator(path),
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


def _runtime_spec(benchmark: str, stage: str) -> RuntimeNoiseSpec:
    path = _project_root() / "benchmark/core1/runtime" / benchmark / f"{stage}.json"
    return RuntimeNoiseSpec.model_validate(_read_object(path))


def _runtime_trace_row(
    *,
    expected_ids: list[str],
    applicable: dict[str, bool],
    reasons: dict[str, str | None],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    covered = sum(applicable.get(task_id) is True for task_id in expected_ids)
    coverage = covered / len(expected_ids) if expected_ids else 0.0
    return {
        "status": "pass" if coverage == 1.0 else "fail",
        "coverage": coverage,
        "applicable_task_ids": [
            task_id for task_id in expected_ids if applicable.get(task_id) is True
        ],
        "inapplicable_reasons": {
            task_id: reasons.get(task_id)
            for task_id in expected_ids
            if applicable.get(task_id) is not True
        },
        "operator_execution": "registered_runtime_mutate_record",
        **provenance,
    }


def _skillopt_task_runtime_applicability(
    *,
    benchmark: str,
    domain: str,
    task_id: str,
    native_row: dict[str, Any],
    conversation: list[dict[str, Any]],
    run_dir: Path,
) -> tuple[Any, Any]:
    """Execute the exact registered SkillOpt N3/N4 selectors provider-free."""

    context = HookContext(
        task_id=task_id,
        benchmark=benchmark,
        domain=domain,
        method="skillopt",
        arm="clean",
        run_dir=run_dir,
    )
    adapter = SkillOptEvidenceAdapter()
    trajectory = adapter.normalize_trajectory(conversation, context)
    n3_result = mutate_record(
        trajectory,
        _enrich_n3_spec(_runtime_spec(benchmark, "N3"), native_row),
    )
    feedback = adapter.normalize_feedback(native_row, context)
    n4_result = mutate_record(
        feedback,
        _enrich_n4_spec(
            _runtime_spec(benchmark, "N4"),
            native_row,
            conversation,
            context,
        ),
        trajectory=trajectory,
    )
    return n3_result.audit, n4_result.audit


def _normalized_task_runtime_applicability(
    *,
    benchmark: str,
    trajectory: TrajectoryRecord,
    feedback: FeedbackRecord,
) -> tuple[Any, Any]:
    """Execute registered N3/N4 on already-normalized baseline evidence."""

    n3_result = mutate_record(trajectory, _runtime_spec(benchmark, "N3"))
    n4_result = mutate_record(
        feedback, _runtime_spec(benchmark, "N4"), trajectory=trajectory
    )
    return n3_result.audit, n4_result.audit


def _strict_trajectory(payload: dict[str, Any]) -> TrajectoryRecord:
    if payload.get("success") is not None and not isinstance(
        payload.get("success"), bool
    ):
        raise ValueError("trajectory success must be a strict boolean")
    reward = payload.get("reward")
    if reward is not None and (
        isinstance(reward, bool)
        or not isinstance(reward, (int, float))
        or not math.isfinite(float(reward))
    ):
        raise ValueError("trajectory reward must be finite")
    return TrajectoryRecord.model_validate(payload)


def _strict_feedback(payload: dict[str, Any]) -> FeedbackRecord:
    reward = payload.get("scalar_reward")
    if reward is not None and (
        isinstance(reward, bool)
        or not isinstance(reward, (int, float))
        or not math.isfinite(float(reward))
    ):
        raise ValueError("feedback scalar reward must be finite")
    return FeedbackRecord.model_validate(payload)


def _skilllearn_execution_row(
    *,
    task_id: str,
    image_payload: dict[str, Any],
    verifier_payload: dict[str, Any],
    hidden_test_exposed: bool,
) -> dict[str, bool]:
    image = SkillLearnImageRecord.model_validate(image_payload)
    if image.task_id != task_id:
        raise ValueError("SkillLearn image task identity differs")
    SkillLearnVerifierRecord.model_validate(verifier_payload)
    return {
        "container_started": True,
        "verifier_completed": True,
        "hidden_test_exposed": hidden_test_exposed,
    }


def _validate_skilladaptor_owned_pair(
    *,
    expected_task_id: str,
    trajectory_payload: dict[str, Any],
    feedback_payload: dict[str, Any],
) -> tuple[TrajectoryRecord, FeedbackRecord]:
    trajectory_wrapper = SkillAdaptorOwnedTrajectory.model_validate(
        trajectory_payload
    )
    feedback_wrapper = SkillAdaptorOwnedFeedback.model_validate(feedback_payload)
    trajectory = _strict_trajectory(trajectory_payload["normalized"])
    feedback = _strict_feedback(feedback_payload["normalized"])
    identities = {
        trajectory_wrapper.task_id,
        feedback_wrapper.task_id,
        trajectory.task_id,
        feedback.task_id,
    }
    if identities != {expected_task_id}:
        raise ValueError("SkillAdaptor owned evidence task identity differs")
    if trajectory.benchmark != "webshop" or feedback.benchmark != "webshop":
        raise ValueError("SkillAdaptor normalized benchmark must be webshop")
    for native in (trajectory_wrapper.native, feedback_wrapper.native):
        native_task_id = native.get("task_id")
        if native_task_id is not None and (
            not isinstance(native_task_id, str)
            or native_task_id != expected_task_id
        ):
            raise ValueError("SkillAdaptor native task identity differs")
    return trajectory, feedback


def _skillopt_batch_membership(
    *,
    benchmark: str,
    method_seed: int,
    expected_ids: list[str],
    actual_batches: list[list[str]],
) -> bool:
    sizes = {
        "spreadsheetbench_verified": (7, 7, 6),
        "officeqa_full": (4, 4, 4),
    }.get(benchmark)
    if (
        sizes is None
        or type(method_seed) is not int
        or len(expected_ids) != sum(sizes)
        or len(actual_batches) != len(sizes)
    ):
        return False
    shuffled_ids = list(expected_ids)
    random.Random(method_seed + 1000).shuffle(shuffled_ids)
    expected_batches: list[list[str]] = []
    offset = 0
    for size in sizes:
        expected_batches.append(shuffled_ids[offset : offset + size])
        offset += size
    # Native workers finish in nondeterministic order within one batch, so the
    # persisted JSONL row order is not an execution-order contract.  The seeded
    # batch allocation and uniqueness are the contract.
    return all(
        len(actual) == len(expected)
        and len(actual) == len(set(actual))
        and set(actual) == set(expected)
        for actual, expected in zip(actual_batches, expected_batches, strict=True)
    )


def _normalized_webshop_query(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def _pinned_webshop_domain_inputs(
    candidate: StableSplitCandidate,
) -> tuple[list[bool], list[bool], list[Path]]:
    """Recompute reachability/headroom from pinned resources, not task flags."""

    project = _project_root()
    goals_path = project / "benchmark/validation/clean_qualification_v1/webshop_source.json"
    selection_path = (
        project
        / "benchmark/validation/clean_qualification_v1/webshop_validation_selection.json"
    )
    products_path = _methods_root(project) / "webshop/data/items_shuffle_1000.json"
    goals_payload = _read_object(goals_path)
    selection = _read_object(selection_path)
    products = json.loads(products_path.read_text(encoding="utf-8"))
    if not isinstance(products, list):
        raise ValueError("pinned WebShop products must be a list")
    query_groups: dict[str, list[str]] = {}
    for product in products[:1000]:
        if not isinstance(product, dict):
            raise ValueError("pinned WebShop product row must be an object")
        asin = product.get("asin")
        query = _normalized_webshop_query(product.get("query"))
        if isinstance(asin, str) and asin and asin != "nan" and len(asin) <= 10:
            query_groups.setdefault(query, []).append(asin)
    goals = goals_payload.get("goals")
    scores = selection.get("candidate_seed_scores")
    if not isinstance(goals, dict) or not isinstance(scores, dict):
        raise ValueError("pinned WebShop audit resources are malformed")
    all_tasks = [
        *candidate.train,
        *candidate.validation,
        *candidate.qualification_test,
    ]
    reachable: list[bool] = []
    for task in all_tasks:
        raw_index = task.task_id.removeprefix("goal_")
        goal = goals.get(raw_index)
        if not isinstance(goal, dict):
            raise ValueError(f"WebShop goal missing from pinned source: {task.task_id}")
        target = goal.get("asin")
        query = _normalized_webshop_query(goal.get("query"))
        if not isinstance(target, str):
            raise ValueError("pinned WebShop goal has malformed ASIN")
        reachable.append(target in query_groups.get(query, [])[:10])
    outcomes: list[bool] = []
    for task in candidate.validation:
        raw_score = scores.get(task.task_id.removeprefix("goal_"))
        if (
            isinstance(raw_score, bool)
            or not isinstance(raw_score, (int, float))
            or not math.isfinite(float(raw_score))
        ):
            raise ValueError(
                f"WebShop validation score missing or malformed: {task.task_id}"
            )
        outcomes.append(float(raw_score) >= 0.999)
    return reachable, outcomes, [goals_path, selection_path, products_path]


def _skillopt_owned_audits_impl(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
    method_seed: int,
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
        batches = [
            [
                SkillOptRolloutRow.model_validate(row)
                for row in _read_jsonl(path)
            ]
            for path in rollout_paths
        ]
        summary = _read_object(summary_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return _missing_owned_audits(
            run_dir, "unreadable_owned_skillopt_trace", evidence_paths
        )
    config = summary.get("config")
    summary_seed = config.get("seed") if isinstance(config, dict) else None
    if type(summary_seed) is not int or summary_seed != method_seed:
        raise ValueError("SkillOpt summary seed differs from validated method seed")
    expected_ids = _ids(candidate.train)
    actual_batches = [[row.id for row in batch] for batch in batches]
    actual_ids = [task_id for batch in actual_batches for task_id in batch]
    exact_global_tasks = _same_unique_ids(actual_ids, expected_ids)
    exact_batches = _skillopt_batch_membership(
        benchmark=candidate.benchmark,
        method_seed=method_seed,
        expected_ids=expected_ids,
        actual_batches=actual_batches,
    )
    exact_tasks = exact_global_tasks and exact_batches
    outcomes = [[bool(row.hard) for row in batch] for batch in batches]
    n3_applicable: dict[str, bool] = {}
    n4_applicable: dict[str, bool] = {}
    n3_reasons: dict[str, str | None] = {}
    n4_reasons: dict[str, str | None] = {}
    patch_coverage = True
    for rollout_path, batch in zip(rollout_paths, batches, strict=True):
        step = rollout_path.parent.parent
        for row in batch:
            task_id = row.id
            conversation_path = step / "rollout/predictions" / task_id / "conversation.json"
            evidence_paths.append(conversation_path)
            if not conversation_path.is_file():
                continue
            raw_conversation = json.loads(
                conversation_path.read_text(encoding="utf-8")
            )
            if not isinstance(raw_conversation, list):
                raise ValueError("SkillOpt conversation must be a list")
            conversation = [
                SkillOptConversationItem.model_validate(item).model_dump(
                    mode="python", exclude_none=True
                )
                for item in raw_conversation
            ]
            native_row = row.model_dump(mode="python")
            n3_audit, n4_audit = _skillopt_task_runtime_applicability(
                benchmark=candidate.benchmark,
                domain=candidate.domain,
                task_id=task_id,
                native_row=native_row,
                conversation=conversation,
                run_dir=step,
            )
            n3_applicable[task_id] = n3_audit.applicable
            n4_applicable[task_id] = n4_audit.applicable
            n3_reasons[task_id] = n3_audit.reason
            n4_reasons[task_id] = n4_audit.reason
        patch_paths = sorted((step / "patches").glob("minibatch_*.json"))
        evidence_paths.extend(patch_paths)
        patch_counts = {"success": 0, "failure": 0}
        for path in patch_paths:
            patch = _read_object(path)
            source_type = patch.get("source_type")
            body = patch.get("patch")
            batch_size = patch.get("batch_size")
            if (
                source_type not in patch_counts
                or not isinstance(body, dict)
                or not body
                or type(batch_size) is not int
                or batch_size < 0
            ):
                patch_coverage = False
                continue
            patch_counts[source_type] += batch_size
        successes = sum(bool(row.hard) for row in batch)
        if patch_counts != {"success": successes, "failure": len(batch) - successes}:
            patch_coverage = False
    provenance = _provenance(run_dir, evidence_paths)
    trace = {
        "N3": _runtime_trace_row(
            expected_ids=expected_ids,
            applicable=n3_applicable if exact_tasks else {},
            reasons=n3_reasons,
            provenance=provenance,
        ),
        "N4": _runtime_trace_row(
            expected_ids=expected_ids,
            applicable=n4_applicable if exact_tasks and patch_coverage else {},
            reasons=n4_reasons,
            provenance=provenance,
        ),
    }
    raw_validation_score = summary.get("baseline_selection_hard")
    if (
        isinstance(raw_validation_score, bool)
        or not isinstance(raw_validation_score, (int, float))
        or not math.isfinite(float(raw_validation_score))
    ):
        raise ValueError("SkillOpt baseline selection score must be finite")
    validation_score = float(raw_validation_score)
    if candidate.benchmark == "spreadsheetbench_verified":
        audit = audit_spreadsheet(
            validation_score=validation_score,
            train_batches=outcomes,
        )
    else:
        parseable = sum(
            bool(str(row.predicted_answer or "").strip())
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
        domain["failure_reasons"].append(
            "owned_train_batch_allocation_differs"
            if exact_global_tasks
            else "owned_train_task_set_differs"
        )
    return trace, domain


def _skillopt_owned_audits(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
    method_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return _skillopt_owned_audits_impl(
            run_dir, candidate=candidate, method_seed=method_seed
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
        return _missing_owned_audits(
            run_dir,
            "unreadable_owned_skillopt_trace",
            [run_dir / "clean/native_train/summary.json"],
        )


def _webshop_owned_audits_impl(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
    runtime: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = run_dir / "clean/webshop_task_manifest.json"
    owned_root = run_dir / "clean/owned_evidence"
    evidence_paths = [manifest_path]
    if not manifest_path.is_file():
        return _missing_owned_audits(
            run_dir, "missing_owned_webshop_trace", evidence_paths
        )
    try:
        manifest = _read_object(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return _missing_owned_audits(
            run_dir, "unreadable_owned_webshop_trace", evidence_paths
        )
    expected_ids = _ids(candidate.train)
    input_tasks = manifest.get("input_tasks")
    if not isinstance(input_tasks, list) or any(
        type(value) is not int for value in input_tasks
    ):
        raise ValueError("WebShop task manifest input_tasks must be integer IDs")
    manifest_ids = [f"goal_{value}" for value in input_tasks]
    exact_tasks = manifest_ids == expected_ids
    n3_applicable: dict[str, bool] = {}
    n4_applicable: dict[str, bool] = {}
    n3_reasons: dict[str, str | None] = {}
    n4_reasons: dict[str, str | None] = {}
    missing_owned_evidence = False
    for task_id in expected_ids:
        trajectory_path = owned_root / task_id / "trajectory.json"
        feedback_path = owned_root / task_id / "feedback.json"
        evidence_paths.extend([trajectory_path, feedback_path])
        if not trajectory_path.is_file() or not feedback_path.is_file():
            missing_owned_evidence = True
            continue
        trajectory_payload = _read_object(trajectory_path)
        feedback_payload = _read_object(feedback_path)
        trajectory, feedback = _validate_skilladaptor_owned_pair(
            expected_task_id=task_id,
            trajectory_payload=trajectory_payload,
            feedback_payload=feedback_payload,
        )
        n3_audit, n4_audit = _normalized_task_runtime_applicability(
            benchmark=candidate.benchmark,
            trajectory=trajectory,
            feedback=feedback,
        )
        n3_applicable[task_id] = n3_audit.applicable
        n4_applicable[task_id] = n4_audit.applicable
        n3_reasons[task_id] = n3_audit.reason
        n4_reasons[task_id] = n4_audit.reason
    provenance = _provenance(run_dir, evidence_paths)
    trace = {
        "N3": _runtime_trace_row(
            expected_ids=expected_ids,
            applicable=n3_applicable if exact_tasks else {},
            reasons=n3_reasons,
            provenance=provenance,
        ),
        "N4": _runtime_trace_row(
            expected_ids=expected_ids,
            applicable=n4_applicable if exact_tasks else {},
            reasons=n4_reasons,
            provenance=provenance,
        ),
    }
    if missing_owned_evidence:
        trace["N3"]["status"] = "missing"
        trace["N4"]["status"] = "missing"
    reachable, validation_outcomes, pinned_paths = _pinned_webshop_domain_inputs(
        candidate
    )
    evidence_paths.extend(pinned_paths)
    provenance = _provenance(run_dir, evidence_paths)
    max_episode_steps = runtime.get("max_episode_steps")
    if type(max_episode_steps) is not int:
        raise ValueError("WebShop max_episode_steps must be an integer")
    audit = audit_webshop(
        target_reachable=reachable,
        validation_outcomes=validation_outcomes,
        max_episode_steps=max_episode_steps,
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
    try:
        return _webshop_owned_audits_impl(
            run_dir, candidate=candidate, runtime=runtime
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
        return _missing_owned_audits(
            run_dir,
            "unreadable_owned_webshop_trace",
            [run_dir / "clean/webshop_task_manifest.json"],
        )


def _skilllearn_owned_audits_impl(
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
    n3_applicable: dict[str, bool] = {}
    n4_applicable: dict[str, bool] = {}
    n3_reasons: dict[str, str | None] = {}
    n4_reasons: dict[str, str | None] = {}
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
        trajectory_payload = _read_object(trajectory_path)
        feedback_payload = _read_object(feedback_path)
        trajectory = _strict_trajectory(trajectory_payload)
        feedback = _strict_feedback(feedback_payload)
        if trajectory.task_id != task_id or feedback.task_id != task_id:
            raise ValueError("SkillLearn visible evidence task identity differs")
        visible = json.dumps(
            [trajectory_payload, feedback_payload], ensure_ascii=False
        ).casefold()
        n3_audit, n4_audit = _normalized_task_runtime_applicability(
            benchmark=candidate.benchmark,
            trajectory=trajectory,
            feedback=feedback,
        )
        n3_applicable[task_id] = n3_audit.applicable
        n4_applicable[task_id] = n4_audit.applicable
        n3_reasons[task_id] = n3_audit.reason
        n4_reasons[task_id] = n4_audit.reason
        executions.append(
            _skilllearn_execution_row(
                task_id=task_id,
                image_payload=_read_object(image_path),
                verifier_payload=_read_object(verifier_path),
                hidden_test_exposed=any(
                    marker in visible for marker in leak_markers
                ),
            )
        )
    if validation_ids:
        validation_dir = run_dir / "clean/validation/round-2" / validation_ids[0]
        image_path = validation_dir / "image/image_record.json"
        verifier_path = validation_dir / "verifier/ctrf.json"
        evidence_paths.extend([image_path, verifier_path])
        if image_path.is_file() and verifier_path.is_file():
            executions.append(
                _skilllearn_execution_row(
                    task_id=validation_ids[0],
                    image_payload=_read_object(image_path),
                    verifier_payload=_read_object(verifier_path),
                    hidden_test_exposed=False,
                )
            )
    if len(round_dirs) < len(train_ids):
        return _missing_owned_audits(
            run_dir, "missing_owned_skilllearn_trace", evidence_paths
        )
    provenance = _provenance(run_dir, evidence_paths)
    trace = {
        "N3": _runtime_trace_row(
            expected_ids=train_ids,
            applicable=n3_applicable,
            reasons=n3_reasons,
            provenance=provenance,
        ),
        "N4": _runtime_trace_row(
            expected_ids=train_ids,
            applicable=n4_applicable,
            reasons=n4_reasons,
            provenance=provenance,
        ),
    }
    audit = audit_skilllearn(executions=executions)
    return trace, {
        **audit.model_dump(mode="json"),
        "evidence_complete": len(executions) == 3,
        **provenance,
    }


def _skilllearn_owned_audits(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
    family: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return _skilllearn_owned_audits_impl(
            run_dir, candidate=candidate, family=family
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
        return _missing_owned_audits(
            run_dir,
            "unreadable_owned_skilllearn_trace",
            [run_dir / "clean/evolution"],
        )


def derive_owned_run_audits(
    run_dir: Path,
    *,
    candidate: StableSplitCandidate,
    family: str | None,
    method_seed: int,
    runtime: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive N3/N4 and domain gates only from baseline-owned persisted outputs."""

    if type(method_seed) is not int:
        raise ValueError("owned audit method_seed must be a strict integer")
    if candidate.benchmark in {"spreadsheetbench_verified", "officeqa_full"}:
        return _skillopt_owned_audits(
            run_dir, candidate=candidate, method_seed=method_seed
        )
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


def _require_contained(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes declared root: {resolved}") from exc
    return resolved


def _find_runtime_identity(run_dir: Path, boundary: Path) -> Path:
    resolved_boundary = boundary.resolve()
    resolved_run = _require_contained(
        run_dir, resolved_boundary, label="clean run directory"
    )
    for parent in (resolved_run, *resolved_run.parents):
        candidate = parent / "runtime_identity.json"
        if candidate.is_file():
            return _require_contained(
                candidate, resolved_boundary, label="runtime identity"
            )
        if parent == resolved_boundary:
            break
    raise FileNotFoundError(f"runtime_identity.json not found above {run_dir}")


def _artifact_path(run_dir: Path, raw: str, *, boundary: Path) -> Path:
    resolved_run = _require_contained(
        run_dir, boundary, label="clean run directory"
    )
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else resolved_run / candidate).resolve()
    _require_contained(resolved, boundary, label="clean artifact")
    return _require_contained(resolved, resolved_run, label="clean artifact")


def _single_seed_artifact(run_dir: Path) -> Path:
    resolved_run = run_dir.resolve()
    seed_dir = _require_contained(
        resolved_run / "seed", resolved_run, label="seed directory"
    )
    seed_files = [path for path in seed_dir.iterdir() if path.is_file()]
    if len(seed_files) != 1:
        raise ValueError("clean run requires exactly one seed artifact")
    return _require_contained(
        seed_files[0], resolved_run, label="seed artifact"
    )


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
    *,
    legacy_reuse: bool = False,
) -> tuple[StableSplitCandidate, int, str | None]:
    benchmark = str(split.get("benchmark") or "")
    if benchmark not in repository.candidates:
        raise ValueError(f"clean run benchmark has no frozen candidate: {benchmark}")
    metadata = split.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    family = str(metadata.get("task_family") or "") or None
    declared = metadata.get("candidate_index")
    if declared is not None and type(declared) is not int:
        raise ValueError("run split candidate_index must be an integer")
    if legacy_reuse:
        if benchmark not in _LEGACY_REUSE_METADATA_ALLOWLIST or family is not None:
            raise ValueError("legacy reuse is restricted to OfficeQA/WebShop Candidate 1")
        if declared not in {None, 1}:
            raise ValueError("legacy reuse is restricted to Candidate 1")
        indexes = [1]
    else:
        indexes = (
            [declared]
            if declared is not None
            else sorted(repository.candidates[benchmark])
        )
    raw_train = split.get("train")
    raw_validation = split.get("validation")
    if not isinstance(raw_train, list) or not isinstance(raw_validation, list):
        raise ValueError("run split train/validation must be task lists")
    actual_train = [TaskManifest.model_validate(row) for row in raw_train]
    actual_validation = [TaskManifest.model_validate(row) for row in raw_validation]
    for index in indexes:
        candidate = repository.candidates[benchmark].get(index)
        if candidate is None:
            continue
        if family:
            allocation = candidate.metadata.get("static_audit", {}).get(
                "family_allocations", {}
            ).get(family, {})
            train_ids = allocation.get("train")
            validation_ids = allocation.get("validation")
            if not isinstance(train_ids, list) or not isinstance(
                validation_ids, list
            ):
                continue
            train_by_id = {task.task_id: task for task in candidate.train}
            validation_by_id = {
                task.task_id: task for task in candidate.validation
            }
            try:
                expected_train = [train_by_id[task_id] for task_id in train_ids]
                expected_validation = [
                    validation_by_id[task_id] for task_id in validation_ids
                ]
            except KeyError:
                continue
        else:
            expected_train = list(candidate.train)
            expected_validation = list(candidate.validation)
        if legacy_reuse:
            _validate_legacy_reuse_candidate(candidate)
            allowlist = _LEGACY_REUSE_METADATA_ALLOWLIST[benchmark]
            if any(
                set(task.metadata) & allowlist
                for task in [*actual_train, *actual_validation]
            ):
                continue
            actual_train_identity = [
                _portable_task_identity(task) for task in actual_train
            ]
            actual_validation_identity = [
                _portable_task_identity(task) for task in actual_validation
            ]
            expected_train_identity = [
                _legacy_reuse_task_identity(task) for task in expected_train
            ]
            expected_validation_identity = [
                _legacy_reuse_task_identity(task) for task in expected_validation
            ]
        else:
            actual_train_identity = [
                _portable_task_identity(task) for task in actual_train
            ]
            actual_validation_identity = [
                _portable_task_identity(task) for task in actual_validation
            ]
            expected_train_identity = [
                _portable_task_identity(task) for task in expected_train
            ]
            expected_validation_identity = [
                _portable_task_identity(task) for task in expected_validation
            ]
        if (
            actual_train_identity == expected_train_identity
            and actual_validation_identity == expected_validation_identity
        ):
            parent_hash = metadata.get("parent_selection_hash")
            if parent_hash is not None and parent_hash != candidate.selection_hash:
                raise ValueError("run split parent selection hash differs")
            return candidate, index, family
    raise ValueError(
        f"clean run TaskManifest content does not match a frozen candidate: {benchmark}"
    )


def read_clean_run(
    run_dir: Path,
    *,
    repository: SelectionRepository,
    boundary: Path,
    legacy_reuse: bool = False,
) -> CleanRunEvidence:
    run_dir = _require_contained(
        run_dir, boundary, label="clean run directory"
    )
    split = _read_object(run_dir / "split_manifest.json")
    candidate, candidate_index, family = _match_candidate(
        repository, split, legacy_reuse=legacy_reuse
    )
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
    method_seed = result.get("method_seed")
    if type(method_seed) is not int:
        raise ValueError("clean result method seed must be an integer")
    if method_seed != identity.inputs.method_seed:
        raise ValueError("clean result method seed differs from runtime identity")
    seed_path = _single_seed_artifact(run_dir)
    seed_hash = sha256_file(seed_path)
    clean_path = _artifact_path(
        run_dir,
        str(artifact.get("skill_path") or ""),
        boundary=boundary,
    )
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
    accepted_update_count = execution.get("accepted_update_count")
    if type(accepted_update_count) is not int or accepted_update_count < 0:
        raise ValueError("accepted_update_count must be a nonnegative integer")
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
        legacy_reuse=legacy_reuse,
    )
    trace_applicability, domain_audit = derive_owned_run_audits(
        run_dir,
        candidate=candidate,
        family=family,
        method_seed=method_seed,
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
    *,
    legacy_reuse: bool = False,
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
                read_clean_run(
                    run_dir,
                    repository=repository,
                    boundary=boundary,
                    legacy_reuse=legacy_reuse,
                )
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


def _candidate_decision_result(
    *,
    repository: SelectionRepository,
    candidate: StableSplitCandidate,
    runs: list[CleanRunEvidence],
    run_root: Path,
    family: str | None = None,
) -> tuple[str, list[str], CandidateDecision | None]:
    group_failures = _group_failures(candidate, runs, family=family)
    retryable_audit, deterministic_audit = _selection_audit_failure_groups(
        repository, candidate, runs
    )
    if group_failures or retryable_audit:
        return sequential_incomplete_action(candidate.candidate_index), [
            *group_failures,
            *retryable_audit,
        ], None
    if deterministic_audit:
        return candidate_failure_action(
            candidate.candidate_index, deterministic=True
        ), deterministic_audit, None
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
        ), None
    if extend:
        return "extend_replay_to_5", ["sign_inconsistent_three_repeat_replay"], None
    decision = decide_candidate(
        candidate_index=candidate.candidate_index,
        seeds=seed_evidence,
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    return decision.next_action, decision.failure_reasons, decision


def _candidate_result(
    *,
    repository: SelectionRepository,
    candidate: StableSplitCandidate,
    runs: list[CleanRunEvidence],
    run_root: Path,
    family: str | None = None,
) -> tuple[str, list[str]]:
    action, reasons, _ = _candidate_decision_result(
        repository=repository,
        candidate=candidate,
        runs=runs,
        run_root=run_root,
        family=family,
    )
    return action, reasons


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
        if action == "run_candidate_3":
            if index == 3:
                return DomainSelectionStatus(
                    benchmark=benchmark,
                    next_action="run_candidate_3",
                    reasons=reasons,
                )
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


def _reuse_index_payload(
    source_root: Path, records: list[CleanRunEvidence]
) -> dict[str, Any]:
    root = source_root.resolve()
    relative_dirs: list[str] = []
    for record in records:
        run_dir = Path(record.run_dir).resolve()
        try:
            relative = run_dir.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"historical clean run is outside declared clean_v2_root: {run_dir}"
            ) from exc
        relative_dirs.append(relative.as_posix())
    relative_dirs = sorted(set(relative_dirs))
    root_identity = canonical_hash(
        {"source_root": str(root), "run_dirs": relative_dirs}
    )
    payload = {
        "schema_version": "rsebench.reuse-run-index.v1",
        "source_root": str(root),
        "source_root_identity": root_identity,
        "run_dirs": relative_dirs,
    }
    return {**payload, "index_hash": canonical_hash(payload)}


def _rehydrate_reused_records(
    run_root: Path, repository: SelectionRepository
) -> list[CleanRunEvidence]:
    """Recompute reusable evidence from immutable historical run directories."""

    index_path = run_root / "reuse_audit_sources.json"
    if not index_path.is_file():
        return []
    raw = _read_object(index_path)
    index = ReuseRunIndex.model_validate(raw)
    unsigned = index.model_dump(mode="json", exclude={"index_hash"})
    if canonical_hash(unsigned) != index.index_hash:
        raise ValueError("reuse run index hash differs")
    source_root = Path(index.source_root).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"declared clean_v2_root is missing: {source_root}")
    expected_root_identity = canonical_hash(
        {"source_root": str(source_root), "run_dirs": index.run_dirs}
    )
    if expected_root_identity != index.source_root_identity:
        raise ValueError("reuse source root identity differs")
    if len(index.run_dirs) != len(set(index.run_dirs)):
        raise ValueError("reuse run index contains duplicate run directories")

    validated_dirs: list[Path] = []
    for relative in index.run_dirs:
        if Path(relative).is_absolute():
            raise ValueError("reuse run index requires relative run directories")
        run_dir = (source_root / relative).resolve()
        try:
            run_dir.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(
                f"historical clean run escapes declared clean_v2_root: {relative}"
            ) from exc
        if not run_dir.is_dir():
            raise FileNotFoundError(f"historical clean run is missing: {run_dir}")
        validated_dirs.append(run_dir)

    expected_identities = _current_candidate_one_identities(repository)
    records: list[CleanRunEvidence] = []
    for run_dir in validated_dirs:
        record = read_clean_run(
            run_dir,
            repository=repository,
            boundary=source_root,
            legacy_reuse=True,
        )
        if (
            record.benchmark not in {"officeqa_full", "webshop"}
            or record.candidate_index != 1
            or record.family is not None
        ):
            continue
        expected = expected_identities.get(
            (record.benchmark, record.method_seed, record.family)
        )
        if expected is None:
            continue
        actual = {
            "baseline_fingerprint": record.baseline_fingerprint,
            "evolution_input_hash": record.evolution_input_hash,
            "provider": record.provider,
            "model": record.model,
            "provider_config_hash": record.provider_config_hash,
            "method_seed": record.method_seed,
            "artifact_hash": record.clean_artifact_hash,
        }
        failures = reuse_identity_failures(
            actual, {**expected, "artifact_hash": record.clean_artifact_hash}
        )
        if record.seed_artifact_hash != expected["seed_artifact_hash"]:
            failures.append("reuse_identity_mismatch:seed_artifact_hash")
        # A stale historical row is never overlaid.  Qualification then
        # reports missing evidence and replay discovery cannot schedule it.
        if failures:
            continue
        records.append(record)
    return records


def _reuse_audit(
    repository: SelectionRepository,
    run_root: Path,
    clean_v2_root: Path | None,
    skillopt_replay_root: Path | None,
) -> SelectionStatus:
    if clean_v2_root is None:
        raise ValueError("reuse-audit requires a declared clean_v2_root")
    records = (
        discover_clean_runs(clean_v2_root, repository, legacy_reuse=True)
        if clean_v2_root is not None
        else []
    )
    expected_identities = _current_candidate_one_identities(repository)
    identity_audits: list[dict[str, Any]] = []
    current_failures: dict[str, list[str]] = {}
    for run in records:
        expected = expected_identities.get(
            (run.benchmark, run.method_seed, run.family)
        )
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
    report_payload = {
        "schema_version": "rsebench.reuse-audit-report.v1",
        "legacy_replays": _legacy_replay_sources(skillopt_replay_root),
        "current_identity_audits": identity_audits,
    }
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "reuse_audit_sources.json").write_text(
        json.dumps(
            _reuse_index_payload(Path(clean_v2_root), records),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_root / "reuse_audit_report.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
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
        group_failures = _group_failures(candidate, runs, family=None)
        identity_failures: list[str] = []
        for run in runs:
            identity_failures.extend(
                current_failures.get(f"{benchmark}:{run.method_seed}", [])
            )
        retryable, deterministic = _selection_audit_failure_groups(
            repository, candidate, runs
        )
        failures = list(
            dict.fromkeys(
                [*group_failures, *identity_failures, *retryable, *deterministic]
            )
        )
        if (
            deterministic
            and not retryable
            and not group_failures
            and not identity_failures
        ):
            next_action = "run_candidate_2"
        else:
            next_action = "rerun_candidate_1" if failures else "replay_candidate_1"
        domains[benchmark] = DomainSelectionStatus(
            benchmark=benchmark,
            next_action=next_action,
            reasons=failures,
        )
    return SelectionStatus(domains=domains)


def _qualification(
    repository: SelectionRepository,
    run_root: Path,
) -> SelectionStatus:
    records = discover_clean_runs(run_root, repository)
    records = _overlay_reused_records(
        records, _rehydrate_reused_records(run_root, repository)
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
    records = _overlay_reused_records(
        records, _rehydrate_reused_records(run_root, repository)
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


def derive_release_qualification_companion(
    *,
    selection_root: Path,
    run_root: Path,
) -> Any:
    """Recompute release decisions and fingerprints from owned clean evidence."""

    repository = load_selection_repository(selection_root)
    root = Path(run_root).resolve()
    stored_status = SelectionStatus.model_validate_json(
        (root / "selection_status.json").read_text(encoding="utf-8")
    )
    derived_status = _qualification(repository, root)
    if stored_status != derived_status:
        raise ValueError("selection status differs from owned qualification evidence")
    if any(
        row.next_action != "freeze_candidate"
        or row.selected_candidate_index is None
        for row in stored_status.domains.values()
    ):
        raise ValueError("release qualification requires four freeze_candidate domains")

    records = discover_clean_runs(root, repository)
    records = _overlay_reused_records(
        records, _rehydrate_reused_records(root, repository)
    )
    decisions: dict[
        str, PoolCandidateDecision | SkillLearnQualificationDecision
    ] = {}
    decision_bases: dict[str, str] = {}
    selection_hashes: dict[str, str] = {}
    selected_indices: dict[str, int] = {}
    evidence_hashes: dict[str, str] = {}
    selected_records: dict[str, list[CleanRunEvidence]] = {}

    for benchmark in POOL_BENCHMARKS:
        selected_index = stored_status.domains[benchmark].selected_candidate_index
        if selected_index is None:
            raise ValueError(f"pool domain has no selected candidate: {benchmark}")
        candidate = repository.candidates[benchmark][selected_index]
        runs = _records_for(records, benchmark, selected_index)
        action, reasons, decision = _candidate_decision_result(
            repository=repository,
            candidate=candidate,
            runs=runs,
            run_root=root,
        )
        if action != "freeze_candidate" or decision is None or not decision.passed:
            raise ValueError(
                f"pool decision is not release-ready: {benchmark}: {reasons}"
            )
        decisions[benchmark] = PoolCandidateDecision(
            benchmark=benchmark,
            decision=decision,
        )
        decision_bases[benchmark] = "candidate_fixed_replay_v1"
        selection_hashes[benchmark] = candidate.selection_hash
        selected_indices[benchmark] = selected_index
        selected_records[benchmark] = runs
        for run in sorted(runs, key=lambda row: row.method_seed):
            evidence_hashes[f"clean:{benchmark}:{run.method_seed}"] = canonical_hash(
                run.model_dump(mode="json")
            )
            replay_path = _replay_result_path(
                root,
                role="qualification_test",
                benchmark=benchmark,
                candidate_index=selected_index,
                method_seed=run.method_seed,
                family=None,
            )
            evidence_hashes[f"replay:{benchmark}:{run.method_seed}"] = sha256_file(
                replay_path
            )

    skill_index = stored_status.domains[
        "skilllearnbench"
    ].selected_candidate_index
    if skill_index != 1:
        raise ValueError("SkillLearn release requires fixed Candidate 1")
    skill_candidate = repository.candidates["skilllearnbench"][1]
    family_summaries: dict[str, SkillLearnFamilyQualificationSummary] = {}
    skill_records: list[CleanRunEvidence] = []
    domain_failure_reasons: list[str] = []
    for family in SKILLLEARN_FAMILIES:
        family_runs = _records_for(records, "skilllearnbench", 1, family)
        skill_records.extend(family_runs)
        group_failures = _group_failures(
            skill_candidate,
            family_runs,
            family=family,
        )
        audit_failures = _selection_audit_failures(
            repository,
            skill_candidate,
            family_runs,
        )
        accepted = sorted(
            run.method_seed
            for run in family_runs
            if run.accepted_update_count > 0
            and run.artifact_changed
            and run.validation_complete
        )
        validation_complete = sorted(
            run.method_seed for run in family_runs if run.validation_complete
        )
        unique_seeds = {run.method_seed for run in family_runs}
        execution_coverage = min(1.0, len(unique_seeds) / len(METHOD_SEEDS))
        noise_applicability = 0.0 if audit_failures else 1.0
        reasons = list(dict.fromkeys([*group_failures, *audit_failures]))
        if len(accepted) < 2:
            reasons.append("fewer_than_two_accepted_updates")
        if execution_coverage != 1.0 or len(validation_complete) != len(METHOD_SEEDS):
            reasons.append("incomplete_family_execution")
        reasons = list(dict.fromkeys(reasons))
        ready = (
            len(accepted) >= 2
            and len(validation_complete) == len(METHOD_SEEDS)
            and execution_coverage == 1.0
            and noise_applicability == 1.0
            and not reasons
        )
        family_evidence_hash = canonical_hash(
            [
                run.model_dump(mode="json")
                for run in sorted(family_runs, key=lambda row: row.method_seed)
            ]
        )
        family_summaries[family] = SkillLearnFamilyQualificationSummary(
            family=family,
            ready=ready,
            accepted_method_seeds=accepted,
            validation_complete_method_seeds=validation_complete,
            execution_coverage=execution_coverage,
            noise_applicability=noise_applicability,
            evidence_hash=family_evidence_hash,
            failure_reasons=reasons,
        )
        domain_failure_reasons.extend(f"{family}:{reason}" for reason in reasons)
        evidence_hashes[f"clean:skilllearnbench:{family}"] = family_evidence_hash
    ready_families = sorted(
        family for family, summary in family_summaries.items() if summary.ready
    )
    qualifying_summaries = [
        family_summaries[family] for family in ready_families
    ]
    skill_execution_coverage = (
        min(summary.execution_coverage for summary in qualifying_summaries)
        if qualifying_summaries
        else 0.0
    )
    skill_noise_applicability = (
        min(summary.noise_applicability for summary in qualifying_summaries)
        if qualifying_summaries
        else 0.0
    )
    skill_passed = (
        len(ready_families) >= 3
        and skill_execution_coverage == 1.0
        and skill_noise_applicability == 1.0
    )
    decisions["skilllearnbench"] = SkillLearnQualificationDecision(
        candidate_index=1,
        required_ready_family_count=3,
        evaluated_family_count=4,
        ready_families=ready_families,
        family_summaries=family_summaries,
        execution_coverage=skill_execution_coverage,
        noise_applicability=skill_noise_applicability,
        passed=skill_passed,
        next_action=(
            "freeze_candidate"
            if skill_passed
            else "clean_blocked_skilllearn_families"
        ),
        failure_reasons=list(dict.fromkeys(domain_failure_reasons)),
    )
    if not skill_passed:
        raise ValueError("SkillLearn fixed-family decision is not release-ready")
    decision_bases["skilllearnbench"] = "skilllearn_fixed_family_gate_v1"
    selection_hashes["skilllearnbench"] = skill_candidate.selection_hash
    selected_indices["skilllearnbench"] = 1
    selected_records["skilllearnbench"] = skill_records

    baseline_by_domain = {
        "skillopt": [
            *selected_records["spreadsheetbench_verified"],
            *selected_records["officeqa_full"],
        ],
        "skilladaptor": selected_records["webshop"],
        "skilllearn_self_feedback": selected_records["skilllearnbench"],
    }
    baseline_fingerprints: dict[str, str] = {}
    for baseline, baseline_records in baseline_by_domain.items():
        fingerprints = {record.baseline_fingerprint for record in baseline_records}
        if len(fingerprints) != 1:
            raise ValueError(f"baseline fingerprints differ in owned runs: {baseline}")
        baseline_fingerprints[baseline] = fingerprints.pop()

    from rsebench.selection.release import make_qualification_release_companion

    return make_qualification_release_companion(
        selection_status=stored_status,
        selected_candidate_indices=selected_indices,
        selection_hashes=selection_hashes,
        decisions=decisions,
        decision_bases=decision_bases,
        baseline_fingerprints=baseline_fingerprints,
        evidence_hashes=evidence_hashes,
    )


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
    records = _overlay_reused_records(
        records, _rehydrate_reused_records(run_root, repository)
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
        candidate = repository.candidates[run.benchmark][run.candidate_index]
        retryable, deterministic = _selection_audit_failure_groups(
            repository, candidate, [run]
        )
        if retryable or deterministic:
            continue
        replay_run_dir = Path(run.run_dir).resolve()
        seed_artifact = _require_contained(
            Path(run.seed_artifact_path),
            replay_run_dir,
            label="replay seed artifact",
        )
        clean_artifact = _require_contained(
            Path(run.clean_artifact_path),
            replay_run_dir,
            label="replay clean artifact",
        )
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
            f"seed={seed_artifact}",
            "--artifact",
            f"clean={clean_artifact}",
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
