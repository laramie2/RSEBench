from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.selection import (
    CandidateDecision,
    ConfirmationSeal,
    ConfirmationSplit,
    ExposureRegistry,
    ResourceLock,
    ResourceReference,
    SelectionReleaseManifest,
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
    roles = {
        role: [_task(benchmark, domain, f"screen-{benchmark}-{role}")]
        for role in (
            "train",
            "validation",
            "qualification_test",
            "screening_test",
        )
    }
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
        metadata={"selection_version": "noise-screen-v1"},
        **roles,
    )


def _confirmation(benchmark: str, domain: str) -> ConfirmationSplit:
    roles = {
        role: [_task(benchmark, domain, f"confirm-{benchmark}-{role}")]
        for role in ("train", "validation", "confirmation_test")
    }
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
        metadata={"selection_version": "noise-screen-v1"},
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
        benchmark: CandidateDecision(
            candidate_index=1,
            passed=True,
            accepted_seed_count=2,
            nondegrading_seed_count=3,
            mean_clean_gain=0.1,
            execution_coverage=1.0,
            noise_applicability=1.0,
            next_action="freeze_candidate",
            failure_reasons=[],
        )
        for benchmark in DOMAINS
    }
    resource_lock = ResourceLock(
        resources=[
            ResourceReference(
                uri="rsebench-data://fixtures/index.json",
                kind="rsebench-data",
                sha256="4" * 64,
                materialization="python scripts/materialize_splits.py",
            ),
            ResourceReference(
                uri="rsebench-methods://skillopt",
                kind="rsebench-methods",
                sha256="5" * 64,
                materialization="python -m rsebench.cli baselines bootstrap",
            ),
            ResourceReference(
                uri="git+https://github.com/example/repo.git@0123456789abcdef",
                kind="git",
                sha256="6" * 64,
                materialization="git clone then verify the pinned revision",
            ),
            ResourceReference(
                uri="oci://registry.example/skilllearn@sha256:" + "7" * 64,
                kind="external-image",
                sha256="7" * 64,
                materialization="docker pull the digest-pinned image",
            ),
        ]
    )
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


def test_release_requires_exact_passing_decisions_and_matching_seal(
    tmp_path: Path, release_inputs: dict[str, Any]
) -> None:
    release_inputs["decisions"]["webshop"] = release_inputs["decisions"][
        "webshop"
    ].model_copy(update={"passed": False, "next_action": "run_candidate_2"})
    with pytest.raises(ValueError, match="passing freeze_candidate decision"):
        freeze_selection_release(destination=tmp_path / "failed", **release_inputs)

    release_inputs["decisions"]["webshop"] = CandidateDecision(
        candidate_index=1,
        passed=True,
        accepted_seed_count=2,
        nondegrading_seed_count=2,
        mean_clean_gain=0.1,
        execution_coverage=1.0,
        noise_applicability=1.0,
        next_action="freeze_candidate",
        failure_reasons=[],
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
        ("worktree.json", b'{"path":"repo/.worktrees/run"}\n', "worktree"),
        ("secret.json", b'{"token":"sk-secret-value"}\n', "secret"),
        ("locator.json", b'{"path":"file:///tmp/data.json"}\n', "unresolved"),
    ],
)
def test_portability_barrier_rejects_forbidden_content(
    name: str, content: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        reject_secrets_and_absolute_paths({name: content})


def test_atomic_writer_rejects_unsafe_relative_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        atomic_content_addressed_write(
            tmp_path / "release", {"../escape.json": b"{}\n"}
        )
