from __future__ import annotations

import importlib.util
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest
import rsebench.selection.qualification_io as qualification_io

from rsebench.contracts import TaskManifest
from rsebench.evidence import FeedbackRecord, TraceEvent, TrajectoryRecord, canonical_hash
from rsebench.selection.contracts import (
    CandidateDecision,
    CandidateSeedEvidence,
    DomainSelectionStatus,
    ExposureRegistry,
    PoolCandidateDecision,
    ScreeningSeedEvidence,
    SelectionStatus,
    SkillLearnQualificationDecision,
    StableSplitCandidate,
)
from rsebench.selection.qualification import (
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
    reuse_action,
    screening_family_ready,
    sequential_incomplete_action,
)
from rsebench.selection.qualification_io import (
    CleanRunEvidence,
    SelectionRepository,
    _group_failures,
    _normalized_task_runtime_applicability,
    _rehydrate_reused_records,
    _reuse_index_payload,
    _selection_audit_failure_groups,
    _skillopt_task_runtime_applicability,
    _strict_feedback,
    _strict_trajectory,
    derive_owned_run_audits,
    normalized_evolution_input_hash,
    SkillOptRolloutRow,
    validate_candidate_denominators,
)


def test_release_companion_rederives_typed_decisions_from_owned_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmarks = {
        "spreadsheetbench_verified": "spreadsheet",
        "officeqa_full": "document",
        "webshop": "interactive",
        "skilllearnbench": "skill_learning",
    }
    candidates = {
        benchmark: StableSplitCandidate(
            benchmark=benchmark,
            domain=domain,
            candidate_index=1,
            train=[],
            validation=[],
            qualification_test=[],
            screening_test=[],
            source_hash=canonical_hash(f"source:{benchmark}"),
            selection_hash=canonical_hash(f"selection:{benchmark}"),
        )
        for benchmark, domain in benchmarks.items()
    }
    repository = SelectionRepository(
        root=tmp_path,
        candidates={benchmark: {1: candidate} for benchmark, candidate in candidates.items()},
        candidate_paths={},
        audits={},
    )
    status = SelectionStatus(
        domains={
            benchmark: DomainSelectionStatus(
                benchmark=benchmark,
                selected_candidate_index=1,
                next_action="freeze_candidate",
            )
            for benchmark in benchmarks
        }
    )
    (tmp_path / "selection_status.json").write_text(status.model_dump_json())
    fingerprints = {
        "spreadsheetbench_verified": "a" * 64,
        "officeqa_full": "a" * 64,
        "webshop": "b" * 64,
        "skilllearnbench": "c" * 64,
    }
    records: list[CleanRunEvidence] = []
    for benchmark in qualification_io.POOL_BENCHMARKS:
        for seed in qualification_io.METHOD_SEEDS:
            records.append(
                CleanRunEvidence(
                    benchmark=benchmark,
                    candidate_index=1,
                    selection_hash=candidates[benchmark].selection_hash,
                    method_seed=seed,
                    run_dir=str(tmp_path / f"{benchmark}-{seed}"),
                    train_task_ids=[],
                    validation_task_ids=[],
                    accepted_update_count=1,
                    artifact_changed=True,
                    validation_complete=True,
                    seed_artifact_path=str(tmp_path / "seed"),
                    seed_artifact_hash="d" * 64,
                    clean_artifact_path=str(tmp_path / "clean"),
                    clean_artifact_hash="e" * 64,
                    baseline_fingerprint=fingerprints[benchmark],
                    evolution_input_hash="f" * 64,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    provider_config_hash="1" * 64,
                )
            )
            replay = qualification_io._replay_result_path(
                tmp_path,
                role="qualification_test",
                benchmark=benchmark,
                candidate_index=1,
                method_seed=seed,
                family=None,
            )
            replay.parent.mkdir(parents=True, exist_ok=True)
            replay.write_text("{}\n")
    for family in qualification_io.SKILLLEARN_FAMILIES:
        for seed in qualification_io.METHOD_SEEDS:
            records.append(
                CleanRunEvidence(
                    benchmark="skilllearnbench",
                    candidate_index=1,
                    selection_hash=candidates["skilllearnbench"].selection_hash,
                    family=family,
                    method_seed=seed,
                    run_dir=str(tmp_path / f"{family}-{seed}"),
                    train_task_ids=[],
                    validation_task_ids=[],
                    accepted_update_count=1,
                    artifact_changed=True,
                    validation_complete=True,
                    seed_artifact_path=str(tmp_path / "seed"),
                    seed_artifact_hash="d" * 64,
                    clean_artifact_path=str(tmp_path / "clean"),
                    clean_artifact_hash="e" * 64,
                    baseline_fingerprint=fingerprints["skilllearnbench"],
                    evolution_input_hash="f" * 64,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    provider_config_hash="1" * 64,
                )
            )
    pool_decision = CandidateDecision(
        candidate_index=1,
        passed=True,
        accepted_seed_count=3,
        nondegrading_seed_count=3,
        mean_clean_gain=0.1,
        execution_coverage=1.0,
        noise_applicability=1.0,
        next_action="freeze_candidate",
        failure_reasons=[],
    )
    monkeypatch.setattr(qualification_io, "load_selection_repository", lambda root: repository)
    monkeypatch.setattr(qualification_io, "_qualification", lambda *args: status)
    monkeypatch.setattr(qualification_io, "discover_clean_runs", lambda *args: records)
    monkeypatch.setattr(qualification_io, "_rehydrate_reused_records", lambda *args: [])
    monkeypatch.setattr(
        qualification_io,
        "_candidate_decision_result",
        lambda **kwargs: ("freeze_candidate", [], pool_decision),
    )
    monkeypatch.setattr(qualification_io, "_group_failures", lambda *args, **kwargs: [])
    failed_family = qualification_io.SKILLLEARN_FAMILIES[-1]

    def audit_failures(repository, candidate, runs):
        del repository, candidate
        return (
            ["incomplete_noise_applicability"]
            if runs and runs[0].family == failed_family
            else []
        )

    monkeypatch.setattr(
        qualification_io,
        "_selection_audit_failures",
        audit_failures,
    )

    companion = qualification_io.derive_release_qualification_companion(
        selection_root=tmp_path,
        run_root=tmp_path,
    )

    assert isinstance(companion.decisions["webshop"], PoolCandidateDecision)
    skilllearn = companion.decisions["skilllearnbench"]
    assert isinstance(skilllearn, SkillLearnQualificationDecision)
    assert len(skilllearn.ready_families) == 3
    assert skilllearn.required_ready_family_count == 3
    assert skilllearn.evaluated_family_count == 4
    assert skilllearn.passed is True
    assert skilllearn.family_summaries[failed_family].ready is False
    assert set(skilllearn.family_summaries) == set(
        qualification_io.SKILLLEARN_FAMILIES
    )
    assert companion.baseline_fingerprints == {
        "skillopt": "a" * 64,
        "skilladaptor": "b" * 64,
        "skilllearn_self_feedback": "c" * 64,
    }


@pytest.fixture(scope="module")
def real_legacy_reuse_cases() -> dict[str, tuple[SelectionRepository, dict]]:
    project = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "rsebench_build_noise_screen_candidates",
        project / "scripts/build_noise_screen_candidates.py",
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    registry = ExposureRegistry(records=[], registry_hash=canonical_hash([]))
    bundles = {
        "officeqa_full": builder._officeqa_bundle(
            exposure_registry=registry,
            data_root=project / "data",
            methods_root=project / "methods/external",
        ),
        "webshop": builder._webshop_bundle(
            exposure_registry=registry,
            data_root=project / "data",
            methods_root=project / "methods/external",
        ),
    }
    split_paths = {
        "officeqa_full": next(
            (
                project
                / "outputs/runs/clean-v2-20260814/attempts"
            ).glob(
                "officeqa-skillopt-20260813-*/*/runner/officeqa_full/"
                "20260813/*/split_manifest.json"
            )
        ),
        "webshop": next(
            (
                project
                / "outputs/runs/clean-v2-20260814/attempts"
            ).glob(
                "webshop-skilladaptor-20260813-*/*/runner/"
                "20260813/*/split_manifest.json"
            )
        ),
    }
    cases: dict[str, tuple[SelectionRepository, dict]] = {}
    for benchmark, bundle in bundles.items():
        candidates = {row.candidate_index: row for row in bundle.candidates}
        repository = SelectionRepository(
            root=project,
            candidates={benchmark: candidates},
            candidate_paths={},
            audits={},
        )
        cases[benchmark] = (
            repository,
            json.loads(split_paths[benchmark].read_text(encoding="utf-8")),
        )
    return cases


@pytest.mark.parametrize("benchmark", ["officeqa_full", "webshop"])
def test_real_historical_manifest_matches_only_explicit_legacy_reuse(
    benchmark: str,
    real_legacy_reuse_cases: dict[str, tuple[SelectionRepository, dict]],
) -> None:
    repository, split = real_legacy_reuse_cases[benchmark]

    with pytest.raises(ValueError, match="frozen candidate"):
        qualification_io._match_candidate(repository, split)

    candidate, index, family = qualification_io._match_candidate(
        repository, split, legacy_reuse=True
    )
    assert candidate.benchmark == benchmark
    assert index == 1
    assert family is None

    common = {
        "candidate": candidate,
        "family": None,
        "runtime": {"legacy_fixture": True},
        "seed_skill_hash": "e" * 64,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
    }
    historical_train = [
        TaskManifest.model_validate(row) for row in split["train"]
    ]
    historical_validation = [
        TaskManifest.model_validate(row) for row in split["validation"]
    ]
    assert normalized_evolution_input_hash(
        **common, legacy_reuse=True
    ) == normalized_evolution_input_hash(
        **common,
        train_tasks=historical_train,
        validation_tasks=historical_validation,
        legacy_reuse=True,
    )
    assert normalized_evolution_input_hash(**common) != normalized_evolution_input_hash(
        **common,
        train_tasks=historical_train,
        validation_tasks=historical_validation,
    )


@pytest.mark.parametrize("benchmark", ["officeqa_full", "webshop"])
def test_legacy_reuse_rejects_every_core_task_field_and_extra_metadata(
    benchmark: str,
    real_legacy_reuse_cases: dict[str, tuple[SelectionRepository, dict]],
) -> None:
    repository, original = real_legacy_reuse_cases[benchmark]
    core_metadata_key = (
        "gold_document_ids" if benchmark == "officeqa_full" else "target_asin"
    )
    corruptions = {
        "prompt": "altered prompt",
        "gold_answers": ["altered gold"],
        "source_hash": "9" * 64,
        "verifier": "altered_verifier",
        "artifact_path": "rsebench-data://altered/artifact.json",
    }
    for field, value in corruptions.items():
        split = json.loads(json.dumps(original))
        split["train"][0][field] = value
        with pytest.raises(ValueError, match="frozen candidate"):
            qualification_io._match_candidate(
                repository, split, legacy_reuse=True
            )
    for key, value in (
        (core_metadata_key, ["altered.txt"] if benchmark == "officeqa_full" else "X"),
        ("unexpected_historical_key", True),
    ):
        split = json.loads(json.dumps(original))
        split["train"][0]["metadata"][key] = value
        with pytest.raises(ValueError, match="frozen candidate"):
            qualification_io._match_candidate(
                repository, split, legacy_reuse=True
            )


@pytest.mark.parametrize("benchmark", ["officeqa_full", "webshop"])
def test_legacy_reuse_independently_rejects_bad_current_derived_annotation(
    benchmark: str,
    real_legacy_reuse_cases: dict[str, tuple[SelectionRepository, dict]],
) -> None:
    repository, split = real_legacy_reuse_cases[benchmark]
    candidate = repository.candidates[benchmark][1]
    first = candidate.train[0]
    derived_key = (
        "officeqa_stratum" if benchmark == "officeqa_full" else "constraint_count"
    )
    bad_task = first.model_copy(
        update={"metadata": {**first.metadata, derived_key: "invalid"}},
        deep=True,
    )
    bad_candidate = candidate.model_copy(
        update={"train": [bad_task, *candidate.train[1:]]}, deep=True
    )
    bad_repository = SelectionRepository(
        root=repository.root,
        candidates={benchmark: {1: bad_candidate}},
        candidate_paths={},
        audits={},
    )

    with pytest.raises(ValueError, match="derived annotation"):
        qualification_io._match_candidate(
            bad_repository, split, legacy_reuse=True
        )


def _frozen_office_repository(tmp_path: Path) -> tuple[SelectionRepository, dict]:
    def task(task_id: str, source_hash: str) -> TaskManifest:
        return TaskManifest(
            task_id=task_id,
            benchmark="officeqa_full",
            domain="document",
            prompt=f"prompt:{task_id}",
            gold_answers=["answer"],
            source_hash=source_hash,
            artifact_path=f"rsebench-data://office/{task_id}.json",
            metadata={"source_files": [f"rsebench-data://office/{task_id}.pdf"]},
        )

    candidate = StableSplitCandidate(
        benchmark="officeqa_full",
        domain="document",
        candidate_index=1,
        train=[task("train-1", "a" * 64)],
        validation=[task("validation-1", "b" * 64)],
        qualification_test=[],
        screening_test=[],
        source_hash="c" * 64,
        selection_hash="d" * 64,
    )
    repository = SelectionRepository(
        root=tmp_path,
        candidates={"officeqa_full": {1: candidate}},
        candidate_paths={},
        audits={},
    )
    split = {
        "benchmark": "officeqa_full",
        "train": [candidate.train[0].model_dump(mode="json")],
        "validation": [candidate.validation[0].model_dump(mode="json")],
        "metadata": {
            "candidate_index": 1,
            "parent_selection_hash": candidate.selection_hash,
        },
    }
    return repository, split


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt", "altered prompt"),
        ("gold_answers", ["altered answer"]),
        ("source_hash", "9" * 64),
        ("metadata", {"source_files": ["rsebench-data://office/other.pdf"]}),
        ("artifact_path", "rsebench-data://office/other.json"),
    ],
)
def test_match_candidate_rejects_stale_task_content(
    tmp_path: Path, field: str, value: object
) -> None:
    repository, split = _frozen_office_repository(tmp_path)
    split["train"][0][field] = value

    with pytest.raises(ValueError, match="frozen candidate"):
        qualification_io._match_candidate(repository, split)


def test_three_identical_stale_manifests_cannot_form_candidate_evidence(
    tmp_path: Path,
) -> None:
    repository, split = _frozen_office_repository(tmp_path)
    candidate = repository.candidates["officeqa_full"][1]
    split["train"][0]["prompt"] = "same stale prompt"

    accepted = []
    for _ in qualification_io.METHOD_SEEDS:
        with pytest.raises(ValueError, match="frozen candidate"):
            qualification_io._match_candidate(repository, split)
    assert qualification_io._group_failures(candidate, accepted, family=None) == [
        "missing_exact_three_method_seeds"
    ]


def test_match_candidate_accepts_resolved_paths_equal_to_frozen_root_uris(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, split = _frozen_office_repository(tmp_path)
    data_root = tmp_path / "data"
    monkeypatch.setenv("RSEBENCH_DATA_ROOT", str(data_root))
    split["train"][0]["artifact_path"] = str(data_root / "office/train-1.json")
    split["train"][0]["metadata"]["source_files"] = [
        str(data_root / "office/train-1.pdf")
    ]
    split["validation"][0]["artifact_path"] = str(
        data_root / "office/validation-1.json"
    )
    split["validation"][0]["metadata"]["source_files"] = [
        str(data_root / "office/validation-1.pdf")
    ]

    candidate, index, family = qualification_io._match_candidate(repository, split)

    assert candidate is repository.candidates["officeqa_full"][1]
    assert index == 1
    assert family is None


def _valid_skilllearn_completion(task_id: str = "family-1") -> tuple[dict, dict]:
    image = {
        "task_id": task_id,
        "context_hash": "a" * 64,
        "image_tag": "rsebench-skilllearn:abc",
        "image_id": "sha256:abc",
        "workdir": "/root",
    }
    verifier = {
        "results": {
            "tool": {"name": "pytest", "version": "8.4.1"},
            "summary": {
                "tests": 2,
                "passed": 1,
                "failed": 1,
                "skipped": 0,
                "pending": 0,
                "other": 0,
                "start": 1.0,
                "stop": 2.0,
            },
            "tests": [
                {"name": "test_ok", "status": "passed", "duration": 0.1},
                {"name": "test_fail", "status": "failed", "duration": 0.2},
            ],
        }
    }
    return image, verifier


def test_skilllearn_completion_requires_strict_image_and_verifier_records() -> None:
    image, verifier = _valid_skilllearn_completion()
    assert qualification_io._skilllearn_execution_row(
        task_id="family-1",
        image_payload=image,
        verifier_payload=verifier,
        hidden_test_exposed=False,
    ) == {
        "container_started": True,
        "verifier_completed": True,
        "hidden_test_exposed": False,
    }

    malformed = [
        ({}, verifier),
        ({**image, "image_id": 1}, verifier),
        ({**image, "task_id": "family-2"}, verifier),
        (image, {}),
        (image, {"results": {}}),
        (
            image,
            {
                "results": {
                    **verifier["results"],
                    "summary": {**verifier["results"]["summary"], "tests": "2"},
                }
            },
        ),
        (
            image,
            {
                "results": {
                    **verifier["results"],
                    "tests": [{"name": "bad", "status": "unknown"}],
                }
            },
        ),
    ]
    for bad_image, bad_verifier in malformed:
        with pytest.raises(ValueError):
            qualification_io._skilllearn_execution_row(
                task_id="family-1",
                image_payload=bad_image,
                verifier_payload=bad_verifier,
                hidden_test_exposed=False,
            )


def test_malformed_skilllearn_completion_becomes_unreadable_owned_audit(
    tmp_path: Path,
) -> None:
    def task(task_id: str) -> TaskManifest:
        return TaskManifest(
            task_id=task_id,
            benchmark="skilllearnbench",
            domain="skill_learning",
            prompt="produce artifact",
            source_hash=canonical_hash(task_id),
            verifier="official:/tests",
            metadata={"task_family": "family"},
        )

    candidate = StableSplitCandidate(
        benchmark="skilllearnbench",
        domain="skill_learning",
        candidate_index=1,
        train=[task("t1"), task("t2")],
        validation=[task("v1")],
        qualification_test=[],
        screening_test=[],
        source_hash="a" * 64,
        selection_hash="b" * 64,
        metadata={
            "static_audit": {
                "family_allocations": {
                    "family": {"train": ["t1", "t2"], "validation": ["v1"]}
                }
            }
        },
    )
    task_dir = tmp_path / "clean/evolution/round-1-t1"
    (task_dir / "execution/image").mkdir(parents=True)
    (task_dir / "execution/verifier").mkdir()
    trajectory = TrajectoryRecord(
        task_id="t1",
        benchmark="skilllearnbench",
        events=[
            TraceEvent(
                event_id="e0",
                step_index=0,
                kind="action",
                action="write",
                tags=["artifact_write"],
            ),
            TraceEvent(
                event_id="e1", step_index=1, kind="action", action="inspect"
            ),
        ],
    )
    feedback = FeedbackRecord(
        task_id="t1",
        benchmark="skilllearnbench",
        blamed_event_ids=["e0"],
    )
    (task_dir / "visible_trajectory.json").write_text(
        trajectory.model_dump_json(), encoding="utf-8"
    )
    (task_dir / "visible_feedback.json").write_text(
        feedback.model_dump_json(), encoding="utf-8"
    )
    (task_dir / "execution/image/image_record.json").write_text(
        "{}", encoding="utf-8"
    )
    _, verifier = _valid_skilllearn_completion("t1")
    (task_dir / "execution/verifier/ctrf.json").write_text(
        json.dumps(verifier), encoding="utf-8"
    )

    trace, domain = qualification_io._skilllearn_owned_audits(
        tmp_path, candidate=candidate, family="family"
    )

    assert trace["N3"]["status"] == trace["N4"]["status"] == "missing"
    assert domain["passed"] is False
    assert domain["failure_reasons"] == ["unreadable_owned_skilllearn_trace"]


def test_malformed_skillopt_row_becomes_unreadable_owned_audit(
    tmp_path: Path,
) -> None:
    tasks = [
        TaskManifest(
            task_id=f"task-{index}",
            benchmark="spreadsheetbench_verified",
            domain="spreadsheet",
            prompt="edit sheet",
            gold_answers=["ok"],
            source_hash=canonical_hash(index),
        )
        for index in range(20)
    ]
    candidate = StableSplitCandidate(
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        candidate_index=1,
        train=tasks,
        validation=[],
        qualification_test=[],
        screening_test=[],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )
    native = tmp_path / "clean/native_train"
    for index in range(1, 4):
        rollout = native / f"steps/step_{index:04d}/rollout"
        rollout.mkdir(parents=True)
        (rollout / "results.jsonl").write_text(
            '{"id":"task-0","hard":"false","soft":0.0}\n'
            if index == 1
            else "",
            encoding="utf-8",
        )
    (native / "summary.json").write_text(
        '{"baseline_selection_hard":0.5}', encoding="utf-8"
    )

    trace, domain = qualification_io._skillopt_owned_audits(
        tmp_path, candidate=candidate, method_seed=20260813
    )

    assert trace["N3"]["status"] == trace["N4"]["status"] == "missing"
    assert domain["failure_reasons"] == ["unreadable_owned_skillopt_trace"]


def test_skillopt_owned_audit_rejects_summary_seed_from_another_run(
    tmp_path: Path,
) -> None:
    tasks = [
        TaskManifest(
            task_id=f"task-{index}",
            benchmark="spreadsheetbench_verified",
            domain="spreadsheet",
            prompt="edit sheet",
            gold_answers=["ok"],
            source_hash=canonical_hash(index),
        )
        for index in range(20)
    ]
    candidate = StableSplitCandidate(
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        candidate_index=1,
        train=tasks,
        validation=[],
        qualification_test=[],
        screening_test=[],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )
    native = tmp_path / "clean/native_train"
    task_ids = [task.task_id for task in tasks]
    random.Random(20260814 + 1000).shuffle(task_ids)
    for index, batch in enumerate((task_ids[:7], task_ids[7:14], task_ids[14:]), 1):
        rollout = native / f"steps/step_{index:04d}/rollout"
        rollout.mkdir(parents=True)
        (rollout / "results.jsonl").write_text(
            "".join(
                json.dumps({"id": task_id, "hard": 0, "soft": 0.0}) + "\n"
                for task_id in batch
            ),
            encoding="utf-8",
        )
    (native / "summary.json").write_text(
        json.dumps(
            {
                "baseline_selection_hard": 0.5,
                "config": {"seed": 20260814},
            }
        ),
        encoding="utf-8",
    )

    trace, domain = qualification_io._skillopt_owned_audits(
        tmp_path, candidate=candidate, method_seed=20260813
    )

    assert trace["N3"]["status"] == trace["N4"]["status"] == "missing"
    assert domain["failure_reasons"] == ["unreadable_owned_skillopt_trace"]


def test_artifact_and_runtime_paths_cannot_escape_run_or_source_root(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    run = source / "run"
    run.mkdir(parents=True)
    inside = run / "clean/skill.md"
    inside.parent.mkdir()
    inside.write_text("skill", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (run / "escape-link").symlink_to(outside)
    seed_dir = run / "seed"
    seed_dir.mkdir()
    (seed_dir / "seed-link").symlink_to(outside)

    assert qualification_io._artifact_path(
        run, "clean/skill.md", boundary=source
    ) == inside.resolve()
    for raw in (str(outside), "../../outside.md", "escape-link"):
        with pytest.raises(ValueError, match="escapes"):
            qualification_io._artifact_path(run, raw, boundary=source)
    with pytest.raises(ValueError, match="escapes"):
        qualification_io._single_seed_artifact(run)

    runtime = source / "runtime_identity.json"
    runtime.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        qualification_io._find_runtime_identity(run, source)


def _owned_webshop_pair(task_id: str = "goal_17") -> tuple[dict, dict]:
    trajectory = {
        "schema_version": "rsebench.skilladaptor-owned-trajectory.v1",
        "task_id": task_id,
        "native": {"task_id": task_id},
        "normalized": {
            "record_type": "trajectory",
            "task_id": task_id,
            "benchmark": "webshop",
            "events": [
                {
                    "event_id": "e0",
                    "step_index": 0,
                    "kind": "action",
                    "action": "search[item]",
                }
            ],
        },
    }
    feedback = {
        "schema_version": "rsebench.skilladaptor-owned-feedback.v1",
        "task_id": task_id,
        "native": {"task_id": task_id},
        "normalized": {
            "record_type": "feedback",
            "task_id": task_id,
            "benchmark": "webshop",
            "blamed_event_ids": ["e0"],
        },
    }
    return trajectory, feedback


def test_webshop_nested_owned_evidence_requires_exact_identity() -> None:
    trajectory, feedback = _owned_webshop_pair()
    normalized_trajectory, normalized_feedback = (
        qualification_io._validate_skilladaptor_owned_pair(
            expected_task_id="goal_17",
            trajectory_payload=trajectory,
            feedback_payload=feedback,
        )
    )
    assert normalized_trajectory.task_id == normalized_feedback.task_id == "goal_17"

    corruptions = [
        ({**trajectory, "task_id": "goal_18"}, feedback),
        (
            {
                **trajectory,
                "normalized": {**trajectory["normalized"], "task_id": "goal_18"},
            },
            feedback,
        ),
        (
            trajectory,
            {**feedback, "normalized": {**feedback["normalized"], "benchmark": "other"}},
        ),
        ({**trajectory, "native": {"task_id": "goal_18"}}, feedback),
        (
            trajectory,
            {**feedback, "normalized": {**feedback["normalized"], "task_id": "goal_18"}},
        ),
    ]
    for bad_trajectory, bad_feedback in corruptions:
        with pytest.raises(ValueError):
            qualification_io._validate_skilladaptor_owned_pair(
                expected_task_id="goal_17",
                trajectory_payload=bad_trajectory,
                feedback_payload=bad_feedback,
            )


@pytest.mark.parametrize(
    ("benchmark", "sizes"),
    [
        ("spreadsheetbench_verified", (7, 7, 6)),
        ("officeqa_full", (4, 4, 4)),
    ],
)
def test_skillopt_batch_membership_rejects_same_global_set_redistribution(
    benchmark: str, sizes: tuple[int, int, int]
) -> None:
    method_seed = 20260813
    task_ids = [f"task-{index}" for index in range(sum(sizes))]
    shuffled = list(task_ids)
    random.Random(method_seed + 1000).shuffle(shuffled)
    exact = []
    offset = 0
    for size in sizes:
        exact.append(shuffled[offset : offset + size])
        offset += size
    completion_order = [list(reversed(batch)) for batch in exact]
    redistributed = [list(batch) for batch in exact]
    redistributed[0][-1], redistributed[1][0] = (
        redistributed[1][0],
        redistributed[0][-1],
    )

    assert qualification_io._skillopt_batch_membership(
        benchmark=benchmark,
        method_seed=method_seed,
        expected_ids=task_ids,
        actual_batches=completion_order,
    )
    assert not qualification_io._skillopt_batch_membership(
        benchmark=benchmark,
        method_seed=method_seed,
        expected_ids=task_ids,
        actual_batches=redistributed,
    )
    duplicated = [list(batch) for batch in exact]
    duplicated[0][-1] = duplicated[0][0]
    assert not qualification_io._skillopt_batch_membership(
        benchmark=benchmark,
        method_seed=method_seed,
        expected_ids=task_ids,
        actual_batches=duplicated,
    )


@pytest.mark.parametrize(
    ("benchmark", "domain", "row", "conversation", "negative_conversation"),
    [
        (
            "spreadsheetbench_verified",
            "spreadsheet",
            {"id": "sheet-1", "hard": 0, "soft": 0.0, "fail_reason": "Wrong range A1"},
            [
                {
                    "role": "assistant",
                    "content": (
                        "load_workbook('/tmp/book.xlsx'); ws['B2'].value = 1; "
                        "wb.save('/tmp/book.xlsx')"
                    ),
                }
            ],
            [
                {
                    "role": "assistant",
                    "content": (
                        "load_workbook('/tmp/book.xlsx'); ws['A1'].value = 1; "
                        "wb.save('/tmp/book.xlsx')"
                    ),
                }
            ],
        ),
        (
            "officeqa_full",
            "document",
            {
                "id": "office-1",
                "hard": 0,
                "soft": 0.0,
                "fail_reason": "Wrong source /docs/a.pdf",
                "source_files": ["/docs/a.pdf"],
            },
            [
                {"type": "tool_call", "cmd": "read('/docs/a.pdf')", "obs": "oracle"},
                {"type": "tool_call", "cmd": "read('/docs/b.pdf')", "obs": "decoy"},
            ],
            [
                {"type": "tool_call", "cmd": "read('/docs/a.pdf')", "obs": "oracle"}
            ],
        ),
    ],
)
def test_skillopt_registered_runtime_applicability_requires_real_decoy(
    tmp_path: Path,
    benchmark: str,
    domain: str,
    row: dict[str, object],
    conversation: list[dict[str, object]],
    negative_conversation: list[dict[str, object]],
) -> None:
    n3, n4 = _skillopt_task_runtime_applicability(
        benchmark=benchmark,
        domain=domain,
        task_id=str(row["id"]),
        native_row=row,
        conversation=conversation,
        run_dir=tmp_path,
    )
    negative_n3, negative_n4 = _skillopt_task_runtime_applicability(
        benchmark=benchmark,
        domain=domain,
        task_id=str(row["id"]),
        native_row=row,
        conversation=negative_conversation,
        run_dir=tmp_path,
    )

    assert n3.applicable is True
    assert n4.applicable is True
    assert negative_n3.applicable is True
    assert negative_n4.applicable is False


@pytest.mark.parametrize(
    ("benchmark", "n3_tag"),
    [("webshop", "required_option"), ("skilllearnbench", "artifact_write")],
)
def test_normalized_domains_require_each_registered_n4_decoy(
    benchmark: str, n3_tag: str
) -> None:
    trajectory = TrajectoryRecord(
        task_id="task-1",
        benchmark=benchmark,
        events=[
            TraceEvent(
                event_id="e0",
                step_index=0,
                kind="action",
                action="write or select",
                tags=[n3_tag],
            ),
            TraceEvent(
                event_id="e1",
                step_index=1,
                kind="action",
                action="inspect",
            ),
        ],
        reward=0.0,
        success=False,
    )
    feedback = FeedbackRecord(
        task_id="task-1",
        benchmark=benchmark,
        blamed_event_ids=["e0"],
        diagnosis="first action failed",
        scalar_reward=0.0,
    )

    n3, n4 = _normalized_task_runtime_applicability(
        benchmark=benchmark, trajectory=trajectory, feedback=feedback
    )
    _, no_decoy = _normalized_task_runtime_applicability(
        benchmark=benchmark,
        trajectory=trajectory.model_copy(update={"events": trajectory.events[:1]}),
        feedback=feedback,
    )

    assert n3.applicable is True
    assert n4.applicable is True
    assert no_decoy.applicable is False


def seed_evidence(
    method_seed: int,
    *,
    accepted: int,
    changed: bool,
    mean_delta: float,
) -> CandidateSeedEvidence:
    return CandidateSeedEvidence(
        method_seed=method_seed,
        accepted_update_count=accepted,
        artifact_changed=changed,
        mean_delta_vs_seed=mean_delta,
        execution_complete=True,
        replay_count=3,
    )


def test_two_updates_two_nondegrading_and_positive_mean_pass() -> None:
    decision = decide_candidate(
        candidate_index=2,
        seeds=[
            seed_evidence(20260813, accepted=1, changed=True, mean_delta=0.08),
            seed_evidence(20260814, accepted=1, changed=True, mean_delta=0.03),
            seed_evidence(20260815, accepted=0, changed=False, mean_delta=0.00),
        ],
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    assert decision.passed is True
    assert decision.next_action == "freeze_candidate"


def test_failed_candidate_two_requests_candidate_three() -> None:
    decision = decide_candidate(
        candidate_index=2,
        seeds=[
            seed_evidence(20260813, accepted=0, changed=False, mean_delta=0.0),
            seed_evidence(20260814, accepted=1, changed=True, mean_delta=0.1),
            seed_evidence(20260815, accepted=0, changed=False, mean_delta=0.0),
        ],
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    assert decision.passed is False
    assert decision.next_action == "run_candidate_3"


def test_failed_candidate_three_fails_closed() -> None:
    decision = decide_candidate(
        candidate_index=3,
        seeds=[
            seed_evidence(seed, accepted=0, changed=False, mean_delta=0.0)
            for seed in (20260813, 20260814, 20260815)
        ],
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    assert decision.passed is False
    assert decision.next_action == "clean_blocked_after_three_candidates"


def test_candidate_requires_exact_three_unique_seeds() -> None:
    repeated = seed_evidence(20260813, accepted=1, changed=True, mean_delta=0.1)
    with pytest.raises(ValueError, match="exactly three unique seeds"):
        decide_candidate(
            candidate_index=1,
            seeds=[repeated, repeated, repeated],
            execution_coverage=1.0,
            noise_applicability=1.0,
        )


def test_sign_inconsistent_three_repeat_replay_extends_to_five() -> None:
    assert replay_action([0.1, -0.1, 0.2], repeats=3) == "extend_replay_to_5"
    assert replay_action([0.1, -0.1, 0.2], repeats=5) == "decide_candidate"


def test_screening_generalization_uses_fixed_three_seed_denominator() -> None:
    ready = decide_screening_generalization(
        seeds=[
            ScreeningSeedEvidence(
                method_seed=20260813,
                mean_delta_vs_seed=0.1,
                execution_complete=True,
                replay_count=3,
            ),
            ScreeningSeedEvidence(
                method_seed=20260814,
                mean_delta_vs_seed=0.0,
                execution_complete=True,
                replay_count=3,
            ),
            ScreeningSeedEvidence(
                method_seed=20260815,
                mean_delta_vs_seed=-0.01,
                execution_complete=True,
                replay_count=3,
            ),
        ],
        execution_coverage=1.0,
    )
    assert ready.status == "clean_generalization_ready"
    assert ready.nondegrading_seed_count == 2
    blocked = decide_screening_generalization(
        seeds=[
            ScreeningSeedEvidence(
                method_seed=seed,
                mean_delta_vs_seed=0.1,
                execution_complete=True,
                replay_count=3,
            )
            for seed in (20260813, 20260814, 20260815)
        ],
        execution_coverage=0.99,
    )
    assert blocked.status == "clean_generalization_failed"
    assert "incomplete_screening_execution_coverage" in blocked.failure_reasons

    zero_mean = decide_screening_generalization(
        seeds=[
            ScreeningSeedEvidence(
                method_seed=seed,
                mean_delta_vs_seed=delta,
                execution_complete=True,
                replay_count=3,
            )
            for seed, delta in zip(
                (20260813, 20260814, 20260815),
                (0.1, 0.0, -0.1),
                strict=True,
            )
        ],
        execution_coverage=1.0,
    )
    assert zero_mean.status == "clean_generalization_failed"
    assert "nonpositive_screening_mean_clean_gain" in zero_mean.failure_reasons


def test_mixed_or_missing_reuse_identity_requests_fixed_fallback_matrix() -> None:
    expected = {
        "baseline_fingerprint": "a" * 64,
        "evolution_input_hash": "b" * 64,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "provider_config_hash": "c" * 64,
        "method_seed": 20260813,
        "artifact_hash": "d" * 64,
    }
    assert reuse_action(expected, expected) == "reuse_artifact"
    mixed = {**expected, "baseline_fingerprint": "e" * 64}
    assert reuse_action(mixed, expected) == "run_fixed_fallback_matrix"
    missing = dict(expected)
    missing.pop("evolution_input_hash")
    assert reuse_action(missing, expected) == "run_fixed_fallback_matrix"


def test_reuse_identity_reports_each_current_field_mismatch() -> None:
    expected = {
        "baseline_fingerprint": "a" * 64,
        "evolution_input_hash": "b" * 64,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "provider_config_hash": "c" * 64,
        "method_seed": 20260813,
        "artifact_hash": "d" * 64,
    }
    actual = {
        **expected,
        "baseline_fingerprint": "e" * 64,
        "provider_config_hash": "f" * 64,
    }
    assert reuse_identity_failures(actual, expected) == [
        "reuse_identity_mismatch:baseline_fingerprint",
        "reuse_identity_mismatch:provider_config_hash",
    ]


def test_normalized_evolution_identity_includes_task_content_not_manifest_path() -> None:
    def task(task_id: str, source_hash: str) -> TaskManifest:
        return TaskManifest(
            task_id=task_id,
            benchmark="officeqa_full",
            domain="document",
            prompt="question",
            gold_answers=["answer"],
            source_hash=source_hash,
            artifact_path=f"rsebench-data://office/{task_id}.json",
        )

    candidate = StableSplitCandidate(
        benchmark="officeqa_full",
        domain="document",
        candidate_index=1,
        train=[task("train-1", "a" * 64)],
        validation=[task("validation-1", "b" * 64)],
        qualification_test=[],
        screening_test=[],
        source_hash="c" * 64,
        selection_hash="d" * 64,
    )
    common = {
        "candidate": candidate,
        "family": None,
        "runtime": {"max_steps": 3},
        "seed_skill_hash": "e" * 64,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
    }
    current = normalized_evolution_input_hash(**common)
    moved_manifest = normalized_evolution_input_hash(
        **common,
        train_tasks=[task("train-1", "a" * 64)],
        validation_tasks=[task("validation-1", "b" * 64)],
    )
    stale_content = normalized_evolution_input_hash(
        **common,
        train_tasks=[task("train-1", "f" * 64)],
        validation_tasks=[task("validation-1", "b" * 64)],
    )

    assert moved_manifest == current
    assert stale_content != current


def test_normalized_identity_portabilizes_roots_and_binds_full_task_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    monkeypatch.setenv("RSEBENCH_DATA_ROOT", str(data_root))

    def item(*, artifact: str, source: str, constraint: str, source_hash: str):
        return TaskManifest(
            task_id="office-1",
            benchmark="officeqa_full",
            domain="document",
            prompt="question",
            gold_answers=["answer"],
            source_hash=source_hash,
            artifact_path=artifact,
            metadata={"source_files": [source], "goal_constraint": constraint},
        )

    portable = item(
        artifact="rsebench-data://office/a/task.json",
        source="rsebench-data://office/a/source.pdf",
        constraint="Q1",
        source_hash="a" * 64,
    )
    candidate = StableSplitCandidate(
        benchmark="officeqa_full",
        domain="document",
        candidate_index=1,
        train=[portable],
        validation=[portable.model_copy(update={"task_id": "office-2"})],
        qualification_test=[],
        screening_test=[],
        source_hash="b" * 64,
        selection_hash="c" * 64,
    )
    common = dict(
        candidate=candidate,
        family=None,
        runtime={"max_steps": 3},
        seed_skill_hash="d" * 64,
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    current = normalized_evolution_input_hash(**common)
    resolved = item(
        artifact=str(data_root / "office/a/task.json"),
        source=str(data_root / "office/a/source.pdf"),
        constraint="Q1",
        source_hash="a" * 64,
    )
    resolved_validation = resolved.model_copy(update={"task_id": "office-2"})

    assert normalized_evolution_input_hash(
        **common, train_tasks=[resolved], validation_tasks=[resolved_validation]
    ) == current
    moved = resolved.model_copy(
        update={"artifact_path": str(data_root / "office/b/task.json")}
    )
    changed_metadata = resolved.model_copy(
        update={"metadata": {**resolved.metadata, "goal_constraint": "Q2"}}
    )
    changed_content = resolved.model_copy(update={"source_hash": "e" * 64})
    assert normalized_evolution_input_hash(
        **common, train_tasks=[moved], validation_tasks=[resolved_validation]
    ) != current
    assert normalized_evolution_input_hash(
        **common,
        train_tasks=[changed_metadata],
        validation_tasks=[resolved_validation],
    ) != current
    assert normalized_evolution_input_hash(
        **common,
        train_tasks=[changed_content],
        validation_tasks=[resolved_validation],
    ) != current


def test_typed_owned_rows_reject_string_booleans_nonfinite_and_bad_nested_shapes() -> None:
    with pytest.raises(ValueError):
        SkillOptRolloutRow.model_validate(
            {"id": "x", "hard": "false", "soft": 0.0}
        )
    with pytest.raises(ValueError):
        SkillOptRolloutRow.model_validate(
            {"id": "x", "hard": 0, "soft": float("nan")}
        )
    with pytest.raises(ValueError):
        SkillOptRolloutRow.model_validate(
            {"id": "x", "hard": 0, "soft": 0.0, "source_files": "a.pdf"}
        )
    with pytest.raises(ValueError):
        _strict_trajectory(
            {
                "task_id": "x",
                "benchmark": "webshop",
                "events": [],
                "success": "false",
            }
        )
    with pytest.raises(ValueError):
        _strict_feedback(
            {
                "task_id": "x",
                "benchmark": "webshop",
                "scalar_reward": float("inf"),
            }
        )


def test_spreadsheet_audit_requires_closed_headroom_and_mixed_batches() -> None:
    passed = audit_spreadsheet(
        validation_score=0.2,
        train_batches=[
            [True, False, False, False, False, False, False],
            [False, True, False, False, False, False, False],
            [False, False, True, False, False, False],
        ],
    )
    assert passed.passed is True
    assert (
        audit_spreadsheet(
            validation_score=0.81,
            train_batches=[[True, False, False]] * 3,
        ).passed
        is False
    )
    assert (
        audit_spreadsheet(
            validation_score=0.5,
            train_batches=[[True, True, True]] * 3,
        ).passed
        is False
    )


def test_officeqa_audit_requires_parseability_headroom_and_mixed_batches() -> None:
    passed = audit_officeqa(
        validation_score=0.75,
        parseable_answer_rate=0.9,
        train_batches=[[True, False, False, False]] * 3,
    )
    assert passed.passed is True
    assert (
        audit_officeqa(
            validation_score=0.5,
            parseable_answer_rate=0.89,
            train_batches=[[True, False, False, False]] * 3,
        ).passed
        is False
    )


def test_webshop_audit_requires_reachability_two_of_five_and_15_steps() -> None:
    passed = audit_webshop(
        target_reachable=[True] * 30,
        validation_outcomes=[True, False, True, False, False],
        max_episode_steps=15,
    )
    assert passed.passed is True
    assert (
        audit_webshop(
            target_reachable=[True, False],
            validation_outcomes=[True, False, True, False, False],
            max_episode_steps=15,
        ).passed
        is False
    )
    assert (
        audit_webshop(
            target_reachable=[True] * 30,
            validation_outcomes=[True, False, False, False, False],
            max_episode_steps=14,
        ).passed
        is False
    )


def test_skilllearn_audit_blocks_incomplete_verifier_or_hidden_test_leakage() -> None:
    ready = audit_skilllearn(
        executions=[
            {
                "container_started": True,
                "verifier_completed": True,
                "hidden_test_exposed": False,
            }
            for _ in range(3)
        ]
    )
    assert ready.passed is True
    leaked = audit_skilllearn(
        executions=[
            {
                "container_started": True,
                "verifier_completed": True,
                "hidden_test_exposed": True,
            }
        ]
    )
    assert leaked.passed is False
    assert "hidden_test_leakage" in leaked.failure_reasons


def test_incomplete_candidate_action_never_regresses_candidate_two_or_three() -> None:
    assert sequential_incomplete_action(1) == "rerun_candidate_1"
    assert sequential_incomplete_action(2) == "run_candidate_2"
    assert sequential_incomplete_action(3) == "run_candidate_3"


def test_completed_candidate_two_domain_failure_advances_to_candidate_three() -> None:
    assert candidate_failure_action(2, deterministic=True) == "run_candidate_3"
    assert candidate_failure_action(2, deterministic=False) == "run_candidate_2"
    assert candidate_failure_action(3, deterministic=False) == "run_candidate_3"
    assert (
        candidate_failure_action(3, deterministic=True)
        == "clean_blocked_after_three_candidates"
    )


def test_skilllearn_screening_readiness_requires_clean_evidence() -> None:
    decision = decide_screening_generalization(
        seeds=[
            ScreeningSeedEvidence(
                method_seed=seed,
                mean_delta_vs_seed=0.1,
                execution_complete=True,
                replay_count=3,
            )
            for seed in (20260813, 20260814, 20260815)
        ],
        execution_coverage=1.0,
    )
    assert screening_family_ready(decision, evidence_failures=[]) is True
    assert (
        screening_family_ready(
            decision, evidence_failures=["incomplete_noise_applicability:N3"]
        )
        is False
    )


def test_replay_integrity_rejects_two_repeats_and_malformed_resume_history() -> None:
    minimal = {
        "repeat_count": 2,
        "duration_seconds": 1.0,
        "task_ids": ["t1"],
        "artifact_hashes": {"seed": "a" * 64, "clean": "b" * 64},
        "observations": [],
        "summaries": {},
        "timing": {"run": {"level": "run"}, "stages": [], "tasks": []},
        "token_usage": {
            "observed_coverage": 1.0,
            "billed_tokens": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        },
        "resume_history": [],
    }
    assert "invalid_replay_repeat_count" in replay_integrity_failures(minimal)
    malformed_resume = {**minimal, "repeat_count": 5, "resume_history": []}
    assert "invalid_replay_resume_history" in replay_integrity_failures(
        malformed_resume
    )


def _span(level: str, name: str, *, task_id: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "level": level,
        "name": name,
        "task_id": task_id,
        "started_at": now,
        "ended_at": now,
        "duration_seconds": 0.1,
        "status": "completed",
        "error_type": None,
        "metadata": {},
    }


def _valid_replay(repeat_count: int = 3) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    hashes = {"seed": "a" * 64, "clean": "b" * 64}
    labels = tuple(hashes)
    task_ids = ["t1", "t2"]
    return {
        "schema_version": "rsebench.fixed-artifact-replay.v1",
        "output_dir": "/tmp/replay",
        "benchmark": "fixture",
        "domain": "document",
        "repeat_count": repeat_count,
        "order_policy": "cyclic_rotation",
        "artifact_order": list(labels),
        "reference_label": "seed",
        "task_ids": task_ids,
        "task_manifest_hash": "c" * 64,
        "artifact_paths": {"seed": "/tmp/seed", "clean": "/tmp/clean"},
        "artifact_hashes": hashes,
        "observations": [
            {
                "repeat": repeat,
                "artifact_label": label,
                "artifact_hash": hashes[label],
                "stage": f"replay_{label}_r{repeat}",
                "started_at": now,
                "ended_at": now,
                "duration_seconds": 0.1,
                "evaluation": {
                    "score": 1.0,
                    "per_task_scores": {task_id: 1.0 for task_id in task_ids},
                    "diagnostics": {},
                },
            }
            for repeat in range(1, repeat_count + 1)
            for label in labels
        ],
        "summaries": {
            label: {
                "scores": [1.0] * repeat_count,
                "mean_score": 1.0,
                "score_sample_stddev": 0.0,
                "min_score": 1.0,
                "max_score": 1.0,
                "deltas_vs_reference": [0.0] * repeat_count,
                "mean_delta_vs_reference": 0.0,
                "delta_sample_stddev": 0.0,
            }
            for label in labels
        },
        "started_at": now,
        "ended_at": now,
        "duration_seconds": 1.0,
        "resume_history": (
            []
            if repeat_count == 3
            else [{"from_repeat_count": 3, "to_repeat_count": 5}]
        ),
        "timing": {
            "run": _span("run", "fixed_artifact_replay"),
            "stages": [
                _span("stage", f"replay_{label}_r{repeat}")
                for repeat in range(1, repeat_count + 1)
                for label in labels
            ],
            "tasks": [
                _span("task", f"replay_{label}_r{repeat}", task_id=task_id)
                for repeat in range(1, repeat_count + 1)
                for label in labels
                for task_id in task_ids
            ],
        },
        "token_usage": {
            "observed_coverage": 1.0,
            "billed_tokens": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        },
    }


@pytest.mark.parametrize("repeat_count", [3, 5])
def test_replay_timing_requires_exact_unique_stage_and_task_sets(
    repeat_count: int,
) -> None:
    stage_substitution = _valid_replay(repeat_count)
    stage_substitution["timing"]["stages"][-1] = stage_substitution["timing"][
        "stages"
    ][0]
    assert "invalid_replay_stage_set" in replay_integrity_failures(
        stage_substitution
    )

    task_substitution = _valid_replay(repeat_count)
    task_substitution["timing"]["tasks"][-1] = task_substitution["timing"][
        "tasks"
    ][0]
    assert "invalid_replay_task_set" in replay_integrity_failures(task_substitution)


def test_reduced_pool_candidate_denominator_is_rejected() -> None:
    def task(task_id: str) -> TaskManifest:
        return TaskManifest(
            task_id=task_id,
            benchmark="officeqa_full",
            domain="document",
            prompt=task_id,
            gold_answers=["answer"],
            source_hash=canonical_hash(task_id),
        )

    candidate = StableSplitCandidate(
        benchmark="officeqa_full",
        domain="document",
        candidate_index=2,
        train=[task("train-1"), task("train-2")],
        validation=[task("validation-1")],
        qualification_test=[task("qualification-1")],
        screening_test=[task("screening-1")],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="wrong fixed denominator"):
        validate_candidate_denominators(candidate)


def test_owned_trace_derivation_never_trusts_preexisting_sidecars(
    tmp_path: Path,
) -> None:
    (tmp_path / "trace_applicability.json").write_text(
        '{"N3":{"status":"pass","coverage":1.0},'
        '"N4":{"status":"pass","coverage":1.0}}',
        encoding="utf-8",
    )
    (tmp_path / "domain_audit.json").write_text(
        '{"passed":true,"failure_reasons":[]}', encoding="utf-8"
    )
    candidate = StableSplitCandidate(
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        candidate_index=1,
        train=[],
        validation=[],
        qualification_test=[],
        screening_test=[],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )

    trace, domain = derive_owned_run_audits(
        tmp_path,
        candidate=candidate,
        family=None,
        method_seed=20260813,
        runtime={"max_steps": 3, "batch_size": 7},
    )

    assert trace["N3"]["status"] == "missing"
    assert trace["N4"]["status"] == "missing"
    assert domain["passed"] is False
    assert domain["evidence_source"] == "owned_persisted_outputs"


def test_webshop_partial_owned_evidence_fails_n3_and_n4_closed(
    tmp_path: Path,
) -> None:
    split = json.loads(
        Path("benchmark/validation/clean_qualification_v2/webshop.json").read_text(
            encoding="utf-8"
        )
    )
    candidate = StableSplitCandidate(
        benchmark="webshop",
        domain="interactive",
        candidate_index=1,
        train=[TaskManifest.model_validate(row) for row in split["train"]],
        validation=[TaskManifest.model_validate(row) for row in split["validation"]],
        qualification_test=[
            TaskManifest.model_validate(row) for row in split["clean_test"]
        ],
        screening_test=[],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "webshop_task_manifest.json").write_text(
        json.dumps(
            {
                "input_tasks": [
                    int(task.task_id.removeprefix("goal_"))
                    for task in candidate.train
                ]
            }
        ),
        encoding="utf-8",
    )
    first = candidate.train[0].task_id
    evidence = clean / "owned_evidence" / first
    evidence.mkdir(parents=True)
    (evidence / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": "rsebench.skilladaptor-owned-trajectory.v1",
                "task_id": first,
                "native": {"task_id": first},
                "normalized": {
                    "record_type": "trajectory",
                    "task_id": first,
                    "benchmark": "webshop",
                    "events": [
                        {
                            "event_id": "step-0",
                            "step_index": 0,
                            "kind": "action",
                            "action": "search[item]",
                            "tags": ["query_refinement"],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    trace, domain = derive_owned_run_audits(
        tmp_path,
        candidate=candidate,
        family=None,
        method_seed=20260813,
        runtime={"max_episode_steps": 15},
    )

    assert trace["N3"]["status"] == "missing"
    assert trace["N4"]["status"] == "missing"
    assert trace["N3"]["coverage"] == 0.0
    assert domain["evidence_source"] == "owned_persisted_outputs"
    assert any(
        row["path"].startswith("rsebench-project://")
        for row in domain["evidence_files"]
    )

    trajectory, feedback = _owned_webshop_pair(first)
    trajectory["normalized"]["benchmark"] = "other"
    (evidence / "trajectory.json").write_text(
        json.dumps(trajectory), encoding="utf-8"
    )
    (evidence / "feedback.json").write_text(json.dumps(feedback), encoding="utf-8")

    malformed_trace, malformed_domain = derive_owned_run_audits(
        tmp_path,
        candidate=candidate,
        family=None,
        method_seed=20260813,
        runtime={"max_episode_steps": 15},
    )
    assert malformed_trace["N3"]["status"] == "missing"
    assert malformed_trace["N4"]["status"] == "missing"
    assert "unreadable_owned_webshop_trace" in malformed_domain["failure_reasons"]


def test_candidate_two_completed_n3_failure_is_deterministic(tmp_path: Path) -> None:
    candidate = StableSplitCandidate(
        benchmark="officeqa_full",
        domain="document",
        candidate_index=2,
        train=[],
        validation=[],
        qualification_test=[],
        screening_test=[],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )
    repository = SelectionRepository(
        root=tmp_path,
        candidates={"officeqa_full": {2: candidate}},
        candidate_paths={},
        audits={
            ("officeqa_full", 2): {
                "static_gates": {
                    "noise_applicability": {
                        "N1": {"status": "pass", "coverage": 1.0},
                        "N2": {"status": "pass", "coverage": 1.0},
                    }
                }
            }
        },
    )
    run = CleanRunEvidence(
        benchmark="officeqa_full",
        candidate_index=2,
        selection_hash=candidate.selection_hash,
        method_seed=20260813,
        run_dir="/run",
        train_task_ids=[],
        validation_task_ids=[],
        accepted_update_count=1,
        artifact_changed=True,
        validation_complete=True,
        seed_artifact_path="/seed",
        seed_artifact_hash="c" * 64,
        clean_artifact_path="/clean",
        clean_artifact_hash="d" * 64,
        baseline_fingerprint="e" * 64,
        evolution_input_hash="f" * 64,
        provider="deepseek",
        model="deepseek-v4-flash",
        provider_config_hash="1" * 64,
        trace_applicability={
            "N3": {"status": "fail", "coverage": 0.5},
            "N4": {"status": "pass", "coverage": 1.0},
        },
        domain_audit={
            "passed": True,
            "evidence_complete": True,
            "failure_reasons": [],
        },
    )

    retryable, deterministic = _selection_audit_failure_groups(
        repository, candidate, [run]
    )

    assert retryable == []
    assert deterministic == ["incomplete_noise_applicability:N3"]
    assert candidate_failure_action(2, deterministic=True) == "run_candidate_3"


def test_skilllearn_seed_group_rejects_mixed_fingerprint_and_family_substitution() -> (
    None
):
    candidate = StableSplitCandidate(
        benchmark="skilllearnbench",
        domain="skill_learning",
        candidate_index=1,
        train=[],
        validation=[],
        qualification_test=[],
        screening_test=[],
        source_hash="a" * 64,
        selection_hash="b" * 64,
    )

    def run(seed: int, *, family: str, fingerprint: str = "c" * 64):
        return CleanRunEvidence(
            benchmark="skilllearnbench",
            candidate_index=1,
            selection_hash=candidate.selection_hash,
            family=family,
            method_seed=seed,
            run_dir=f"/run/{seed}",
            train_task_ids=["train"],
            validation_task_ids=["validation"],
            accepted_update_count=1,
            artifact_changed=True,
            validation_complete=True,
            seed_artifact_path=f"/seed/{seed}",
            seed_artifact_hash="d" * 64,
            clean_artifact_path=f"/clean/{seed}",
            clean_artifact_hash="e" * 64,
            baseline_fingerprint=fingerprint,
            evolution_input_hash="f" * 64,
            provider="deepseek",
            model="deepseek-v4-flash",
            provider_config_hash="1" * 64,
        )

    records = [
        run(20260813, family="organize-messy-files"),
        run(
            20260814,
            family="organize-messy-files",
            fingerprint="9" * 64,
        ),
        run(20260815, family="substituted-family"),
    ]

    failures = _group_failures(
        candidate,
        records,
        family="organize-messy-files",
    )

    assert "mixed_clean_identity:baseline_fingerprint" in failures
    assert "run_family_substituted" in failures


def test_reuse_index_rehydrates_from_run_dir_and_rejects_cached_evidence_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "clean-v2"
    historical = source_root / "run-1"
    historical.mkdir(parents=True)
    run_root = tmp_path / "selection-run"
    run_root.mkdir()
    record = CleanRunEvidence(
        benchmark="officeqa_full",
        candidate_index=1,
        selection_hash="a" * 64,
        method_seed=20260813,
        run_dir=str(historical),
        train_task_ids=["train"],
        validation_task_ids=["validation"],
        accepted_update_count=1,
        artifact_changed=True,
        validation_complete=True,
        seed_artifact_path=str(historical / "seed.md"),
        seed_artifact_hash="b" * 64,
        clean_artifact_path=str(historical / "clean.md"),
        clean_artifact_hash="c" * 64,
        baseline_fingerprint="d" * 64,
        evolution_input_hash="e" * 64,
        provider="deepseek",
        model="deepseek-v4-flash",
        provider_config_hash="f" * 64,
    )
    repository = SelectionRepository(
        root=tmp_path,
        candidates={},
        candidate_paths={},
        audits={},
    )
    monkeypatch.setattr(qualification_io, "read_clean_run", lambda *args, **kwargs: record)
    monkeypatch.setattr(
        qualification_io,
        "_current_candidate_one_identities",
        lambda repository: {
            ("officeqa_full", 20260813, None): {
                "baseline_fingerprint": record.baseline_fingerprint,
                "evolution_input_hash": record.evolution_input_hash,
                "provider": record.provider,
                "model": record.model,
                "provider_config_hash": record.provider_config_hash,
                "method_seed": record.method_seed,
                "seed_artifact_hash": record.seed_artifact_hash,
            }
        },
    )
    index = _reuse_index_payload(source_root, [record])
    (run_root / "reuse_audit_sources.json").write_text(
        json.dumps(index), encoding="utf-8"
    )

    assert _rehydrate_reused_records(run_root, repository) == [record]

    monkeypatch.setattr(
        qualification_io,
        "_current_candidate_one_identities",
        lambda repository: {},
    )
    assert _rehydrate_reused_records(run_root, repository) == []

    # Old sidecar evidence fields cannot override recomputed run evidence.
    tampered = {**index, "runs": [{"artifact_changed": False}]}
    (run_root / "reuse_audit_sources.json").write_text(
        json.dumps(tampered), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        _rehydrate_reused_records(run_root, repository)
    with pytest.raises(ValueError):
        qualification_io._qualification(repository, run_root)
    monkeypatch.setattr(
        qualification_io, "load_selection_repository", lambda path: repository
    )
    with pytest.raises(ValueError):
        qualification_io.discover_replay_jobs(
            selection_root=tmp_path / "selection",
            run_root=run_root,
            evaluation_role="qualification_test",
            candidate_index=1,
            repeats=3,
            resume=False,
        )


def test_reuse_index_rejects_escape_missing_run_and_current_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "clean-v2"
    source_root.mkdir()
    run_root = tmp_path / "selection-run"
    run_root.mkdir()
    repository = SelectionRepository(
        root=tmp_path,
        candidates={},
        candidate_paths={},
        audits={},
    )

    def write_index(run_dirs: list[str]) -> None:
        unsigned = {
            "schema_version": "rsebench.reuse-run-index.v1",
            "source_root": str(source_root),
            "source_root_identity": canonical_hash(
                {"source_root": str(source_root), "run_dirs": run_dirs}
            ),
            "run_dirs": run_dirs,
        }
        (run_root / "reuse_audit_sources.json").write_text(
            json.dumps({**unsigned, "index_hash": canonical_hash(unsigned)}),
            encoding="utf-8",
        )

    write_index(["../outside"])
    with pytest.raises(ValueError, match="escapes"):
        _rehydrate_reused_records(run_root, repository)
    write_index(["missing"])
    with pytest.raises(FileNotFoundError, match="historical clean run is missing"):
        _rehydrate_reused_records(run_root, repository)

    historical = source_root / "run-1"
    historical.mkdir()
    stale = CleanRunEvidence(
        benchmark="officeqa_full",
        candidate_index=1,
        selection_hash="a" * 64,
        method_seed=20260813,
        run_dir=str(historical),
        train_task_ids=[],
        validation_task_ids=[],
        accepted_update_count=1,
        artifact_changed=True,
        validation_complete=True,
        seed_artifact_path="/seed",
        seed_artifact_hash="b" * 64,
        clean_artifact_path="/clean",
        clean_artifact_hash="c" * 64,
        baseline_fingerprint="d" * 64,
        evolution_input_hash="e" * 64,
        provider="deepseek",
        model="deepseek-v4-flash",
        provider_config_hash="f" * 64,
    )
    monkeypatch.setattr(qualification_io, "read_clean_run", lambda *args, **kwargs: stale)
    monkeypatch.setattr(
        qualification_io,
        "_current_candidate_one_identities",
        lambda repository: {
            ("officeqa_full", 20260813, None): {
                "baseline_fingerprint": "9" * 64,
                "evolution_input_hash": stale.evolution_input_hash,
                "provider": stale.provider,
                "model": stale.model,
                "provider_config_hash": stale.provider_config_hash,
                "method_seed": stale.method_seed,
                "seed_artifact_hash": stale.seed_artifact_hash,
            }
        },
    )
    write_index(["run-1"])
    assert _rehydrate_reused_records(run_root, repository) == []


def test_reuse_and_replay_planning_skip_ineligible_owned_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def candidate(benchmark: str, domain: str) -> StableSplitCandidate:
        return StableSplitCandidate(
            benchmark=benchmark,
            domain=domain,
            candidate_index=1,
            train=[],
            validation=[],
            qualification_test=[],
            screening_test=[],
            source_hash=canonical_hash(f"source:{benchmark}"),
            selection_hash=canonical_hash(f"selection:{benchmark}"),
        )

    office = candidate("officeqa_full", "document")
    webshop = candidate("webshop", "interactive")
    static = {
        "static_gates": {
            "noise_applicability": {
                "N1": {"status": "pass", "coverage": 1.0},
                "N2": {"status": "pass", "coverage": 1.0},
            }
        }
    }
    repository = SelectionRepository(
        root=tmp_path,
        candidates={
            "officeqa_full": {1: office},
            "webshop": {1: webshop},
        },
        candidate_paths={},
        audits={
            ("officeqa_full", 1): static,
            ("webshop", 1): static,
        },
    )
    clean_root = tmp_path / "clean-v2"
    clean_root.mkdir()

    def run(
        item: StableSplitCandidate, seed: int, *, missing_trace: bool
    ) -> CleanRunEvidence:
        run_dir = clean_root / f"{item.benchmark}-{seed}"
        run_dir.mkdir()
        return CleanRunEvidence(
            benchmark=item.benchmark,
            candidate_index=1,
            selection_hash=item.selection_hash,
            method_seed=seed,
            run_dir=str(run_dir),
            train_task_ids=[],
            validation_task_ids=[],
            accepted_update_count=1,
            artifact_changed=True,
            validation_complete=True,
            seed_artifact_path=str(run_dir / "seed"),
            seed_artifact_hash="a" * 64,
            clean_artifact_path=str(run_dir / "clean"),
            clean_artifact_hash="b" * 64,
            baseline_fingerprint="c" * 64,
            evolution_input_hash="d" * 64,
            provider="deepseek",
            model="deepseek-v4-flash",
            provider_config_hash="e" * 64,
            trace_applicability={
                stage: {
                    "status": "missing" if missing_trace else "pass",
                    "coverage": 0.0 if missing_trace else 1.0,
                }
                for stage in ("N3", "N4")
            },
            domain_audit=(
                {"passed": True, "evidence_complete": True, "failure_reasons": []}
                if missing_trace
                else {
                    "passed": False,
                    "evidence_complete": True,
                    "failure_reasons": ["train_batch_not_mixed:1"],
                }
            ),
        )

    records = [
        *[run(office, seed, missing_trace=False) for seed in qualification_io.METHOD_SEEDS],
        *[run(webshop, seed, missing_trace=True) for seed in qualification_io.METHOD_SEEDS],
    ]
    expected = {
        (record.benchmark, record.method_seed, None): {
            "baseline_fingerprint": record.baseline_fingerprint,
            "evolution_input_hash": record.evolution_input_hash,
            "provider": record.provider,
            "model": record.model,
            "provider_config_hash": record.provider_config_hash,
            "method_seed": record.method_seed,
            "seed_artifact_hash": record.seed_artifact_hash,
        }
        for record in records
    }
    discovery_modes: list[bool] = []

    def discover(*args, **kwargs):
        del args
        discovery_modes.append(bool(kwargs.get("legacy_reuse", False)))
        return records

    monkeypatch.setattr(qualification_io, "discover_clean_runs", discover)
    monkeypatch.setattr(
        qualification_io, "_current_candidate_one_identities", lambda repository: expected
    )

    run_root = tmp_path / "selection-run"
    status = qualification_io._reuse_audit(
        repository, run_root, clean_root, None
    )
    assert discovery_modes == [True]
    assert status.domains["officeqa_full"].next_action == "run_candidate_2"
    assert status.domains["webshop"].next_action == "rerun_candidate_1"

    # The shared audit gate runs before any paid replay job is emitted.
    (run_root / "reuse_audit_sources.json").unlink()
    monkeypatch.setattr(
        qualification_io, "load_selection_repository", lambda path: repository
    )
    jobs = qualification_io.discover_replay_jobs(
        selection_root=tmp_path / "selection",
        run_root=run_root,
        evaluation_role="qualification_test",
        candidate_index=1,
        repeats=3,
        resume=False,
    )
    assert jobs == []

    # Even an otherwise eligible row cannot forward an artifact from outside
    # its clean run into a replay command.
    bad = records[0].model_copy(
        update={"seed_artifact_path": str(tmp_path / "outside-seed.md")}
    )
    records[:] = [bad]
    monkeypatch.setattr(
        qualification_io,
        "_selection_audit_failure_groups",
        lambda *args, **kwargs: ([], []),
    )
    with pytest.raises(ValueError, match="replay seed artifact escapes"):
        qualification_io.discover_replay_jobs(
            selection_root=tmp_path / "selection",
            run_root=run_root,
            evaluation_role="qualification_test",
            candidate_index=1,
            repeats=3,
            resume=False,
        )
