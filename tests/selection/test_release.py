from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.selection import (
    CandidateDecision,
    ConfirmationSeal,
    ConfirmationSplit,
    ExposureLevel,
    ExposureRecord,
    ExposureRegistry,
    PoolCandidateDecision,
    ResourceLock,
    ResourceReference,
    SelectionReleaseManifest,
    SkillLearnFamilyQualificationSummary,
    SkillLearnQualificationDecision,
    StableSplitCandidate,
)
from rsebench.selection.release import (
    atomic_content_addressed_write,
    freeze_selection_release,
    reject_secrets_and_absolute_paths,
)


DOMAINS = {
    "spreadsheetbench_verified": "spreadsheet",
    "officeqa_full": "document",
    "webshop": "interactive",
    "skilllearnbench": "skill_learning",
}
BASELINES = {
    "skillopt": "1" * 64,
    "skilladaptor": "2" * 64,
    "skilllearn_self_feedback": "3" * 64,
}


def _task(benchmark: str, domain: str, task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain=domain,
        prompt=f"Prompt for {task_id}",
        gold_answers=["answer"],
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
        artifact_path=f"rsebench-data://fixtures/{benchmark}/{task_id}.json",
    )


def _candidate(benchmark: str, domain: str, index: int = 1) -> StableSplitCandidate:
    if benchmark == "skilllearnbench":
        families = (
            "organize-messy-files",
            "offer-letter-generator",
            "schedule-planning",
            "dependency-vulnerability-check",
        )
        roles = {
            role: []
            for role in (
                "train",
                "validation",
                "qualification_test",
                "screening_test",
            )
        }
        allocations = {}
        for family in families:
            family_roles = {
                "train": [f"{family}-train-{item}" for item in range(2)],
                "validation": [f"{family}-validation-0"],
                "screening_test": [f"{family}-screen-{item}" for item in range(2)],
            }
            allocations[family] = family_roles
            for role, task_ids in family_roles.items():
                roles[role].extend(
                    _task(benchmark, domain, task_id).model_copy(
                        update={"metadata": {"task_family": family}}
                    )
                    for task_id in task_ids
                )
        metadata = {
            "selection_version": "noise-screen-v1",
            "families": list(families),
            "static_audit": {"family_allocations": allocations},
        }
    else:
        counts = {
            "spreadsheetbench_verified": (20, 10, 30, 30),
            "officeqa_full": (12, 12, 20, 20),
            "webshop": (5, 5, 20, 20),
        }[benchmark]
        roles = {
            role: [
                _task(benchmark, domain, f"screen-{benchmark}-{role}-{item}")
                for item in range(count)
            ]
            for role, count in zip(
                ("train", "validation", "qualification_test", "screening_test"),
                counts,
                strict=True,
            )
        }
        metadata = {"selection_version": "noise-screen-v1"}
    ordered_ids = {
        role: [task.task_id for task in tasks] for role, tasks in roles.items()
    }
    return StableSplitCandidate(
        benchmark=benchmark,
        domain=domain,
        candidate_index=index,
        source_hash=canonical_hash(
            {
                role: [task.model_dump(mode="json") for task in tasks]
                for role, tasks in roles.items()
            }
        ),
        selection_hash=canonical_hash(ordered_ids),
        metadata=metadata,
        **roles,
    )


def _confirmation(benchmark: str, domain: str) -> ConfirmationSplit:
    if benchmark == "skilllearnbench":
        families = (
            "court-form-filling",
            "earthquake-plate-calculation",
            "dbscan-parameter-tuning",
            "travel-planning",
        )
        roles = {
            role: [] for role in ("train", "validation", "confirmation_test")
        }
        for family in families:
            family_counts = {"train": 2, "validation": 1, "confirmation_test": 2}
            for role, count in family_counts.items():
                roles[role].extend(
                    _task(
                        benchmark,
                        domain,
                        f"confirm-{family}-{role}-{item}",
                    ).model_copy(update={"metadata": {"task_family": family}})
                    for item in range(count)
                )
        metadata = {
            "selection_version": "noise-screen-v1",
            "families": list(families),
        }
    else:
        counts = {
            "spreadsheetbench_verified": (20, 10, 30),
            "officeqa_full": (12, 12, 20),
            "webshop": (5, 5, 20),
        }[benchmark]
        roles = {
            role: [
                _task(benchmark, domain, f"confirm-{benchmark}-{role}-{item}")
                for item in range(count)
            ]
            for role, count in zip(
                ("train", "validation", "confirmation_test"),
                counts,
                strict=True,
            )
        }
        metadata = {"selection_version": "noise-screen-v1"}
    ordered_ids = {
        role: [task.task_id for task in tasks] for role, tasks in roles.items()
    }
    return ConfirmationSplit(
        benchmark=benchmark,
        domain=domain,
        source_hash=canonical_hash(
            {
                role: [task.model_dump(mode="json") for task in tasks]
                for role, tasks in roles.items()
            }
        ),
        selection_hash=canonical_hash(ordered_ids),
        metadata=metadata,
        **roles,
    )


def _seal(
    confirmations: dict[str, ConfirmationSplit], registry: ExposureRegistry
) -> ConfirmationSeal:
    split_hashes: dict[str, str] = {}
    task_ids: dict[str, list[str]] = {}
    for benchmark, confirmation in sorted(confirmations.items()):
        for role in ("train", "validation", "confirmation_test"):
            tasks = list(getattr(confirmation, role))
            key = f"{benchmark}:{role}"
            split_hashes[key] = canonical_hash(
                [task.model_dump(mode="json") for task in tasks]
            )
            task_ids[key] = [task.task_id for task in tasks]
    return ConfirmationSeal(
        created_before_screening=True,
        split_hashes=split_hashes,
        task_ids=task_ids,
        exposure_registry_hash=registry.registry_hash,
    )


def make_release_inputs() -> dict[str, Any]:
    candidates = {
        benchmark: _candidate(benchmark, domain)
        for benchmark, domain in DOMAINS.items()
    }
    confirmations = {
        benchmark: _confirmation(benchmark, domain)
        for benchmark, domain in DOMAINS.items()
    }
    registry = ExposureRegistry(records=[], registry_hash=canonical_hash([]))
    decisions = {
        benchmark: PoolCandidateDecision(
            benchmark=benchmark,
            decision=CandidateDecision(
                candidate_index=1,
                passed=True,
                accepted_seed_count=2,
                nondegrading_seed_count=3,
                mean_clean_gain=0.1,
                execution_coverage=1.0,
                noise_applicability=1.0,
                next_action="freeze_candidate",
                failure_reasons=[],
            ),
        )
        for benchmark in DOMAINS
        if benchmark != "skilllearnbench"
    }
    families = (
        "organize-messy-files",
        "offer-letter-generator",
        "schedule-planning",
        "dependency-vulnerability-check",
    )
    decisions["skilllearnbench"] = SkillLearnQualificationDecision(
        candidate_index=1,
        ready_families=list(families[:3]),
        family_summaries={
            family: SkillLearnFamilyQualificationSummary(
                family=family,
                ready=family in families[:3],
                accepted_method_seeds=[20260813, 20260814],
                validation_complete_method_seeds=[
                    20260813,
                    20260814,
                    20260815,
                ],
                execution_coverage=1.0,
                noise_applicability=1.0,
                evidence_hash=hashlib.sha256(family.encode()).hexdigest(),
                failure_reasons=(
                    [] if family in families[:3] else ["fewer_than_two_accepted_updates"]
                ),
            )
            for family in families
        },
        execution_coverage=1.0,
        noise_applicability=1.0,
        passed=True,
        next_action="freeze_candidate",
        failure_reasons=[],
    )
    task_uris = sorted(
        {
            task.artifact_path
            for split in [*candidates.values(), *confirmations.values()]
            for role in (
                ("train", "validation", "confirmation_test")
                if isinstance(split, ConfirmationSplit)
                else ("train", "validation", "qualification_test", "screening_test")
            )
            for task in getattr(split, role)
        }
    )
    resources = [
        ResourceReference(
            uri=uri,
            kind="rsebench-data",
            sha256=hashlib.sha256(uri.encode()).hexdigest(),
            materialization=uri,
        )
        for uri in task_uris
    ]
    for index, baseline in enumerate(sorted(BASELINES), start=1):
        resources.append(
            ResourceReference(
                uri=(
                    f"git+https://github.com/example/{baseline}.git@"
                    f"{str(index) * 40}"
                ),
                kind="git",
                sha256=str(index + 3) * 64,
                materialization=f"rsebench-methods://{baseline}",
            )
        )
    skill_task_ids = sorted(
        {
            task.task_id
            for split in (
                candidates["skilllearnbench"],
                confirmations["skilllearnbench"],
            )
            for role in (
                ("train", "validation", "confirmation_test")
                if isinstance(split, ConfirmationSplit)
                else ("train", "validation", "qualification_test", "screening_test")
            )
            for task in getattr(split, role)
        }
    )
    resources.append(
        ResourceReference(
            uri="oci://registry.example/rsebench/skilllearn@sha256:" + "7" * 64,
            kind="external-image",
            sha256="7" * 64,
            materialization="docker-image://sha256:" + "7" * 64,
            task_ids=skill_task_ids,
        )
    )
    resource_lock = ResourceLock(resources=resources)
    return {
        "candidates": candidates,
        "confirmations": confirmations,
        "decisions": decisions,
        "domain_statuses": {
            benchmark: "clean_generalization_ready" for benchmark in DOMAINS
        },
        "exposure_registry": registry,
        "confirmation_seal": _seal(confirmations, registry),
        "resource_lock": resource_lock,
        "baseline_fingerprints": dict(BASELINES),
    }


@pytest.fixture
def release_inputs() -> dict[str, Any]:
    return make_release_inputs()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _rehash_candidate(candidate: StableSplitCandidate) -> StableSplitCandidate:
    roles = {
        role: list(getattr(candidate, role))
        for role in ("train", "validation", "qualification_test", "screening_test")
    }
    return candidate.model_copy(
        update={
            "source_hash": canonical_hash(
                {
                    role: [task.model_dump(mode="json") for task in tasks]
                    for role, tasks in roles.items()
                }
            ),
            "selection_hash": canonical_hash(
                {role: [task.task_id for task in tasks] for role, tasks in roles.items()}
            ),
        }
    )


def _rehash_confirmation(confirmation: ConfirmationSplit) -> ConfirmationSplit:
    roles = {
        role: list(getattr(confirmation, role))
        for role in ("train", "validation", "confirmation_test")
    }
    return confirmation.model_copy(
        update={
            "source_hash": canonical_hash(
                {
                    role: [task.model_dump(mode="json") for task in tasks]
                    for role, tasks in roles.items()
                }
            ),
            "selection_hash": canonical_hash(
                {role: [task.task_id for task in tasks] for role, tasks in roles.items()}
            ),
        }
    )


def _replace_registry(
    release_inputs: dict[str, Any], records: list[ExposureRecord]
) -> None:
    registry = ExposureRegistry(
        records=records,
        registry_hash=canonical_hash(
            [record.model_dump(mode="json") for record in records]
        ),
    )
    release_inputs["exposure_registry"] = registry
    release_inputs["confirmation_seal"] = _seal(
        release_inputs["confirmations"], registry
    )


def test_release_rejects_nonready_domain(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    release_inputs["domain_statuses"]["webshop"] = "clean_generalization_failed"

    with pytest.raises(ValueError, match="clean_generalization_ready"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)

    assert not (tmp_path / "release").exists()


def test_release_is_portable_content_addressed_and_complete(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    frozen = freeze_selection_release(
        destination=tmp_path / "release", **release_inputs
    )

    files = _tree_bytes(tmp_path / "release")
    payload = (tmp_path / "release" / "manifest.json").read_text()
    assert str(tmp_path) not in payload
    assert ".worktrees" not in payload
    assert len(frozen.release_id) == 64
    assert frozen.file_hashes == {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted(files.items())
    }
    assert frozen.release_id == canonical_hash(
        [[name, digest] for name, digest in sorted(frozen.file_hashes.items())]
    )
    assert set(files) == {
        "manifest.json",
        "exposure_registry.json",
        "confirmation_seal.json",
        "resource_lock.json",
        *{f"base_splits/{benchmark}.json" for benchmark in DOMAINS},
        *{f"confirmation_splits/{benchmark}.json" for benchmark in DOMAINS},
        *{f"candidate_decisions/{benchmark}.json" for benchmark in DOMAINS},
    }
    manifest = json.loads(payload)
    assert "release_id" not in manifest
    assert manifest["selected_candidate_indices"] == {
        benchmark: 1 for benchmark in DOMAINS
    }
    assert manifest["baseline_fingerprints"] == BASELINES
    SelectionReleaseManifest.model_validate(manifest)
    for benchmark in DOMAINS:
        StableSplitCandidate.model_validate_json(
            files[f"base_splits/{benchmark}.json"]
        )
        ConfirmationSplit.model_validate_json(
            files[f"confirmation_splits/{benchmark}.json"]
        )


def test_release_is_idempotent_but_refuses_differing_existing_destination(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    destination = tmp_path / "release"
    first = freeze_selection_release(destination=destination, **release_inputs)
    repeated = freeze_selection_release(destination=destination, **release_inputs)
    assert repeated == first

    (destination / "manifest.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="existing release content differs"):
        freeze_selection_release(destination=destination, **release_inputs)


def test_release_rejects_cross_release_overlap(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    benchmark = "webshop"
    candidate = release_inputs["candidates"][benchmark]
    confirmation = release_inputs["confirmations"][benchmark]
    release_inputs["confirmations"][benchmark] = confirmation.model_copy(
        update={"train": [candidate.train[0]]}
    )

    with pytest.raises(ValueError, match="screening and confirmation.*disjoint"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


@pytest.mark.parametrize("hash_field", ["source_hash", "selection_hash"])
@pytest.mark.parametrize("split_kind", ["candidate", "confirmation"])
def test_release_recomputes_split_hashes(
    tmp_path: Path,
    release_inputs: dict[str, Any],
    hash_field: str,
    split_kind: str,
) -> None:
    mapping_name = "candidates" if split_kind == "candidate" else "confirmations"
    row = release_inputs[mapping_name]["webshop"]
    release_inputs[mapping_name]["webshop"] = row.model_copy(
        update={hash_field: "f" * 64}
    )

    with pytest.raises(ValueError, match=hash_field):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


def test_release_rejects_wrong_preregistered_task_count(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    candidate = release_inputs["candidates"]["webshop"]
    release_inputs["candidates"]["webshop"] = _rehash_candidate(
        candidate.model_copy(update={"train": list(candidate.train[:-1])})
    )

    with pytest.raises(ValueError, match="WebShop.*5/5/20"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


def test_release_requires_fixed_skilllearn_confirmation_families(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    confirmation = release_inputs["confirmations"]["skilllearnbench"]
    bad_task = confirmation.train[0].model_copy(
        update={"metadata": {"task_family": "substituted-family"}}
    )
    release_inputs["confirmations"]["skilllearnbench"] = _rehash_confirmation(
        confirmation.model_copy(update={"train": [bad_task, *confirmation.train[1:]]})
    )
    release_inputs["confirmation_seal"] = _seal(
        release_inputs["confirmations"], release_inputs["exposure_registry"]
    )

    with pytest.raises(ValueError, match="confirmation families"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


def test_release_rejects_historically_executed_confirmation_task(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    task = release_inputs["confirmations"]["officeqa_full"].confirmation_test[0]
    _replace_registry(
        release_inputs,
        [
            ExposureRecord(
                benchmark="officeqa_full",
                task_id=task.task_id,
                level=ExposureLevel.executed,
                roles=["test"],
                sources=["history"],
            )
        ],
    )

    with pytest.raises(ValueError, match="confirmation.*historically executed"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


def test_release_rejects_score_observed_pool_screening_task(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    task = release_inputs["candidates"]["webshop"].screening_test[0]
    _replace_registry(
        release_inputs,
        [
            ExposureRecord(
                benchmark="webshop",
                task_id=task.task_id,
                level=ExposureLevel.score_observed,
                roles=["test"],
                sources=["history"],
            )
        ],
    )

    with pytest.raises(ValueError, match="screening.*score_observed"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


def test_skilllearn_exposure_exception_rejects_nonfixed_screening_family(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    candidate = release_inputs["candidates"]["skilllearnbench"]
    bad_task = candidate.screening_test[0].model_copy(
        update={"metadata": {"task_family": "github-repo-analytics"}}
    )
    release_inputs["candidates"]["skilllearnbench"] = _rehash_candidate(
        candidate.model_copy(
            update={"screening_test": [bad_task, *candidate.screening_test[1:]]}
        )
    )

    with pytest.raises(ValueError, match="SkillLearn screening families"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


def test_release_requires_exact_passing_decisions_and_matching_seal(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    pool = release_inputs["decisions"]["webshop"]
    release_inputs["decisions"]["webshop"] = pool.model_copy(
        update={
            "decision": pool.decision.model_copy(
                update={"passed": False, "next_action": "run_candidate_2"}
            )
        }
    )
    with pytest.raises(ValueError, match="passing freeze_candidate decision"):
        freeze_selection_release(destination=tmp_path / "failed", **release_inputs)

    release_inputs["decisions"]["webshop"] = PoolCandidateDecision(
        benchmark="webshop",
        decision=CandidateDecision(
            candidate_index=1,
            passed=True,
            accepted_seed_count=2,
            nondegrading_seed_count=2,
            mean_clean_gain=0.1,
            execution_coverage=1.0,
            noise_applicability=1.0,
            next_action="freeze_candidate",
            failure_reasons=[],
        ),
    )
    release_inputs["confirmation_seal"] = release_inputs[
        "confirmation_seal"
    ].model_copy(update={"exposure_registry_hash": "f" * 64})
    with pytest.raises(ValueError, match="exposure registry"):
        freeze_selection_release(destination=tmp_path / "bad-seal", **release_inputs)


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("absolute.json", b'{"path":"/home/user/data.json"}\n', "absolute path"),
        ("embedded.json", b'{"path":"prefix=/home/user/data"}\n', "absolute path"),
        ("etc.json", b'{"path":"prefix=/etc/passwd"}\n', "absolute path"),
        (
            "windows.json",
            b'{"path":"prefix=C:\\\\Users\\\\person\\\\data"}\n',
            "absolute path",
        ),
        ("worktree.json", b'{"prompt":"repo/.worktrees/run"}\n', "worktree"),
        ("secret.json", b'{"prompt":"sk-secret-value"}\n', "secret"),
        ("locator.json", b'{"path":"file:///tmp/data.json"}\n', "unresolved"),
        (
            "userinfo.json",
            b'{"prompt":"git+https://token@example.com/x"}\n',
            "userinfo",
        ),
    ],
)
def test_portability_barrier_rejects_forbidden_content(
    name: str, content: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        reject_secrets_and_absolute_paths({name: content})


def test_portability_barrier_allows_non_path_slashes_and_https_urls() -> None:
    reject_secrets_and_absolute_paths(
        {
            "portable.json": json.dumps(
                {
                    "prompt": "Compute 10 / 2 and cite https://example.com/reference",
                    "uri": "rsebench-data://portable/task.json",
                }
            ).encode()
        }
    )


def test_portability_barrier_allows_absolute_path_literals_in_prose() -> None:
    reject_secrets_and_absolute_paths(
        {
            "prompts.json": json.dumps(
                {
                    "prompt": "Read /root/test_input.json and write rows under /out/.",
                    "instruction": (
                        r"The example mentions C:\Users\person\input.json verbatim."
                    ),
                }
            ).encode()
        }
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"artifact_path": "/home/user/artifact.json"},
        {"metadata": {"locator": "/etc/passwd"}},
        {"metadata": {"materialization": r"C:\Users\person\artifact.json"}},
        {"metadata": {"paths": {"input": "/etc/passwd"}}},
        {"uri": "/etc/passwd"},
    ],
)
def test_portability_barrier_rejects_nested_path_bearing_fields(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="absolute path"):
        reject_secrets_and_absolute_paths(
            {"path-bearing.json": json.dumps(payload).encode()}
        )


def test_portability_barrier_rejects_machine_home_path_in_prompt() -> None:
    content = json.dumps({"prompt": "Debug output saved at /home/user/run.json"}).encode()
    with pytest.raises(ValueError, match="machine path"):
        reject_secrets_and_absolute_paths({"machine.json": content})


def test_portability_barrier_accepts_all_preregistered_task7_splits() -> None:
    project_root = Path(__file__).resolve().parents[2]
    selection_root = project_root / "benchmark/validation/noise_screen_v1"
    paths = [
        *sorted((selection_root / "candidates").glob("**/*.json")),
        *sorted((selection_root / "confirmation").glob("*.json")),
    ]

    assert len(paths) == 14
    reject_secrets_and_absolute_paths(
        {
            path.relative_to(selection_root).as_posix(): path.read_bytes()
            for path in paths
        }
    )


def test_atomic_writer_rejects_unsafe_relative_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        atomic_content_addressed_write(
            tmp_path / "release", {"../escape.json": b"{}\n"}
        )


@pytest.mark.parametrize(
    "credential_field",
    [
        "apiKey",
        "api-key",
        "accessToken",
        "secret_key",
        "privateKey",
        "password",
        "token",
        "auth_token",
        "secret",
        "credential",
        "authorization",
    ],
)
def test_portability_barrier_rejects_credential_field_variants(
    credential_field: str,
) -> None:
    content = json.dumps({credential_field: "credential-value"}).encode()
    with pytest.raises(ValueError, match="secret credential field"):
        reject_secrets_and_absolute_paths({"secret.json": content})


def test_atomic_writer_rejects_destination_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    destination = tmp_path / "release"
    destination.symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlink"):
        atomic_content_addressed_write(destination, {"manifest.json": b"{}\n"})


def test_atomic_writer_rejects_parent_symlink(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="parent.*symlink"):
        atomic_content_addressed_write(
            linked_parent / "release", {"manifest.json": b"{}\n"}
        )


@pytest.mark.parametrize(
    "uri",
    [
        "rsebench-data://",
        "rsebench-data://../private",
        "git+https://",
        "oci://",
    ],
)
def test_resource_reference_rejects_reviewer_uri_probes(uri: str) -> None:
    kind = (
        "rsebench-data"
        if uri.startswith("rsebench-data")
        else "git"
        if uri.startswith("git")
        else "external-image"
    )
    with pytest.raises(ValidationError):
        ResourceReference(
            uri=uri,
            kind=kind,
            sha256="a" * 64,
            materialization="fixture",
        )


@pytest.mark.parametrize(
    "uri",
    [
        "git+https://example.com/repository.git?token=value@" + "a" * 40,
        "git+https://example.com/repository.git#fragment@" + "a" * 40,
        "git+https://example.com/repository%2egit@" + "a" * 40,
        "git+https://example.com/%75ser/repository.git@" + "a" * 40,
    ],
)
def test_resource_reference_rejects_non_repository_git_uri_characters(
    uri: str,
) -> None:
    with pytest.raises(ValidationError):
        ResourceReference(
            uri=uri,
            kind="git",
            sha256="a" * 64,
            materialization="rsebench-methods://skillopt",
        )


def test_release_resource_lock_requires_all_task_artifacts(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    missing = release_inputs["candidates"]["webshop"].train[0].artifact_path
    lock = release_inputs["resource_lock"]
    release_inputs["resource_lock"] = ResourceLock(
        resources=[resource for resource in lock.resources if resource.uri != missing]
    )

    with pytest.raises(ValueError, match="resource lock lacks required portable resources"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


def test_release_resource_lock_requires_three_baseline_git_pins(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    lock = release_inputs["resource_lock"]
    release_inputs["resource_lock"] = ResourceLock(
        resources=[
            resource
            for resource in lock.resources
            if resource.materialization != "rsebench-methods://skilladaptor"
        ]
    )

    with pytest.raises(ValueError, match="baseline git pins"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)


def test_release_resource_lock_requires_skilllearn_image_coverage(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    lock = release_inputs["resource_lock"]
    resources = []
    for resource in lock.resources:
        if resource.kind == "external-image":
            resource = resource.model_copy(update={"task_ids": list(resource.task_ids[1:])})
        resources.append(resource)
    release_inputs["resource_lock"] = ResourceLock(resources=resources)

    with pytest.raises(ValueError, match="SkillLearn image coverage"):
        freeze_selection_release(destination=tmp_path / "release", **release_inputs)
