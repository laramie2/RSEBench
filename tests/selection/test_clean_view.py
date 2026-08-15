from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.selection import StableSplitCandidate
from rsebench.selection.clean_view import load_clean_runtime_view


def _task(task_id: str, *, benchmark: str, domain: str, family: str | None = None):
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain=domain,
        prompt=task_id,
        gold_answers=["answer"] if domain != "skill_learning" else [],
        verifier="skilllearn_hidden_test_v1" if domain == "skill_learning" else None,
        source_hash=canonical_hash(task_id),
        metadata={"task_family": family} if family is not None else {},
    )


def _write(path: Path, payload) -> Path:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _hash_roles(roles: dict[str, list[TaskManifest]]) -> str:
    return canonical_hash(
        {
            name: [task.model_dump(mode="json") for task in tasks]
            for name, tasks in roles.items()
        }
    )


def _pool_candidate(*, qualification: bool = True) -> StableSplitCandidate:
    qualification_tasks = (
        [_task("qualification", benchmark="fixture", domain="document")]
        if qualification
        else []
    )
    roles = {
        "train": [_task("train", benchmark="fixture", domain="document")],
        "validation": [_task("validation", benchmark="fixture", domain="document")],
        "qualification_test": qualification_tasks,
        "screening_test": [_task("screening", benchmark="fixture", domain="document")],
    }
    return StableSplitCandidate(
        benchmark="fixture",
        domain="document",
        candidate_index=2,
        source_hash=_hash_roles(roles),
        selection_hash=canonical_hash(
            {name: [task.task_id for task in tasks] for name, tasks in roles.items()}
        ),
        metadata={
            "qualification_version": "noise-screen-v1",
            "source_seed": 17,
            "runtime": {"workers": 1},
            "baseline": "fixture",
        },
        **roles,
    )


def _skilllearn_candidate() -> StableSplitCandidate:
    families = ("alpha", "beta")
    train = [
        _task(
            f"{family}-{index}",
            benchmark="skilllearnbench",
            domain="skill_learning",
            family=family,
        )
        for family in families
        for index in (1, 2)
    ]
    validation = [
        _task(
            f"{family}-3",
            benchmark="skilllearnbench",
            domain="skill_learning",
            family=family,
        )
        for family in families
    ]
    screening = [
        _task(
            f"{family}-4",
            benchmark="skilllearnbench",
            domain="skill_learning",
            family=family,
        )
        for family in families
    ]
    roles = {
        "train": train,
        "validation": validation,
        "qualification_test": [],
        "screening_test": screening,
    }
    return StableSplitCandidate(
        benchmark="skilllearnbench",
        domain="skill_learning",
        candidate_index=1,
        source_hash=_hash_roles(roles),
        selection_hash=canonical_hash(
            {name: [task.task_id for task in tasks] for name, tasks in roles.items()}
        ),
        metadata={
            "qualification_version": "noise-screen-v1",
            "source_seed": 19,
            "runtime": {
                "evolution_rounds": 2,
                "max_completion_tokens": 4096,
                "max_tool_turns": 16,
                "require_prebuilt_images": True,
            },
            "baseline": "skilllearn_self_feedback",
            "feedback_mode": "self",
            "families": list(families),
            "static_audit": {
                "family_allocations": {
                    family: {
                        "train": [f"{family}-1", f"{family}-2"],
                        "validation": [f"{family}-3"],
                        "screening_test": [f"{family}-4"],
                    }
                    for family in families
                }
            },
        },
        **roles,
    )


def test_pool_runtime_view_uses_qualification_ids_and_never_screening(
    tmp_path: Path,
) -> None:
    candidate = _pool_candidate()

    view = load_clean_runtime_view(_write(tmp_path / "candidate.json", candidate))

    assert [task.task_id for task in view.clean_test] == ["qualification"]
    assert "screening" not in view.model_dump_json()
    assert view.seed == 17
    assert view.metadata["parent_selection_hash"] == candidate.selection_hash


def test_pool_runtime_view_rejects_empty_qualification_test(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty qualification_test"):
        load_clean_runtime_view(
            _write(tmp_path / "candidate.json", _pool_candidate(qualification=False))
        )


def test_skilllearn_runtime_view_is_family_scoped_validation_only(
    tmp_path: Path,
) -> None:
    candidate = _skilllearn_candidate()

    view = load_clean_runtime_view(
        _write(tmp_path / "candidate.json", candidate),
        family="alpha",
    )

    assert [task.task_id for task in view.train] == ["alpha-1", "alpha-2"]
    assert [task.task_id for task in view.validation] == ["alpha-3"]
    assert view.clean_test == []
    assert view.metadata["evaluation_mode"] == "validation_only"
    assert view.metadata["task_family"] == "alpha"
    assert view.metadata["parent_selection_hash"] == candidate.selection_hash
    assert "alpha-4" not in view.model_dump_json()
    assert "beta-" not in view.model_dump_json()


def test_skilllearn_runtime_view_requires_known_explicit_family(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "candidate.json", _skilllearn_candidate())

    with pytest.raises(ValueError, match="explicit family"):
        load_clean_runtime_view(path)
    with pytest.raises(ValueError, match="unknown SkillLearn family"):
        load_clean_runtime_view(path, family="gamma")


def test_skilllearn_runtime_view_rejects_family_audit_mismatch(tmp_path: Path) -> None:
    candidate = _skilllearn_candidate()
    payload = candidate.model_dump(mode="json")
    payload["metadata"]["static_audit"]["family_allocations"]["alpha"]["train"] = [
        "alpha-2",
        "alpha-1",
    ]

    with pytest.raises(ValueError, match="family allocation differs"):
        load_clean_runtime_view(
            _write(tmp_path / "candidate.json", payload),
            family="alpha",
        )


def test_legacy_clean_manifest_loads_unchanged(tmp_path: Path) -> None:
    split = CleanEvolutionSplitManifest(
        benchmark="fixture",
        domain="document",
        seed=7,
        source_hash="a" * 64,
        train=[_task("train", benchmark="fixture", domain="document")],
        validation=[_task("validation", benchmark="fixture", domain="document")],
        clean_test=[_task("test", benchmark="fixture", domain="document")],
        metadata={"qualification_version": "clean-qualification-v2"},
    )

    loaded = load_clean_runtime_view(_write(tmp_path / "legacy.json", split))

    assert loaded == split
