"""Typed runtime views over legacy clean splits and frozen selection candidates."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.selection.contracts import StableSplitCandidate


def _runtime_source_hash(*, train: list[Any], validation: list[Any], clean_test: list[Any]) -> str:
    return canonical_hash(
        {
            "train": [task.model_dump(mode="json") for task in train],
            "validation": [task.model_dump(mode="json") for task in validation],
            "clean_test": [task.model_dump(mode="json") for task in clean_test],
        }
    )


def _source_seed(candidate: StableSplitCandidate) -> int:
    value = candidate.metadata.get("source_seed")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("selection candidate metadata requires integer source_seed")
    return value


def _runtime_metadata(candidate: StableSplitCandidate) -> dict[str, Any]:
    keys = (
        "qualification_version",
        "selection_version",
        "runtime",
        "baseline",
        "feedback_mode",
    )
    metadata = {
        key: _plain(candidate.metadata[key])
        for key in keys
        if key in candidate.metadata
    }
    metadata.update(
        {
            "candidate_index": candidate.candidate_index,
            "parent_selection_hash": candidate.selection_hash,
            "parent_source_hash": candidate.source_hash,
        }
    )
    return metadata


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(child) for child in value]
    return value


def _plain_task(task: TaskManifest) -> TaskManifest:
    return TaskManifest.model_validate(_plain(task.model_dump(mode="python")))


def _pool_view(candidate: StableSplitCandidate) -> CleanEvolutionSplitManifest:
    if not candidate.qualification_test:
        raise ValueError("pool selection candidate requires non-empty qualification_test")
    clean_test = [_plain_task(task) for task in candidate.qualification_test]
    train = [_plain_task(task) for task in candidate.train]
    validation = [_plain_task(task) for task in candidate.validation]
    return CleanEvolutionSplitManifest(
        benchmark=candidate.benchmark,
        domain=candidate.domain,
        seed=_source_seed(candidate),
        source_hash=_runtime_source_hash(
            train=train,
            validation=validation,
            clean_test=clean_test,
        ),
        train=train,
        validation=validation,
        clean_test=clean_test,
        metadata=_runtime_metadata(candidate),
    )


def _family_task_ids(tasks: list[Any], family: str) -> list[str]:
    return [
        task.task_id
        for task in tasks
        if str(task.metadata.get("task_family") or "") == family
    ]


def _skilllearn_view(
    candidate: StableSplitCandidate,
    *,
    family: str | None,
) -> CleanEvolutionSplitManifest:
    if not family:
        raise ValueError("SkillLearn selection candidate requires explicit family")
    families = candidate.metadata.get("families")
    if not isinstance(families, Sequence) or isinstance(families, str) or family not in families:
        raise ValueError(f"unknown SkillLearn family: {family}")
    if candidate.qualification_test:
        raise ValueError("SkillLearn selection candidate qualification_test must be empty")
    static_audit = candidate.metadata.get("static_audit")
    allocations = (
        static_audit.get("family_allocations")
        if isinstance(static_audit, Mapping)
        else None
    )
    allocation = allocations.get(family) if isinstance(allocations, Mapping) else None
    if not isinstance(allocation, Mapping):
        raise ValueError(f"SkillLearn family allocation is missing: {family}")
    roles = {
        "train": _family_task_ids(candidate.train, family),
        "validation": _family_task_ids(candidate.validation, family),
        "screening_test": _family_task_ids(candidate.screening_test, family),
    }
    for role, actual in roles.items():
        expected = allocation.get(role)
        if (
            not isinstance(expected, Sequence)
            or isinstance(expected, str)
            or actual != list(expected)
        ):
            raise ValueError(f"SkillLearn {family} family allocation differs: {role}")
    train_ids = set(roles["train"])
    validation_ids = set(roles["validation"])
    train = [_plain_task(task) for task in candidate.train if task.task_id in train_ids]
    validation = [
        _plain_task(task)
        for task in candidate.validation
        if task.task_id in validation_ids
    ]
    metadata = {
        **_runtime_metadata(candidate),
        "task_family": family,
        "evaluation_mode": "validation_only",
    }
    return CleanEvolutionSplitManifest(
        benchmark=candidate.benchmark,
        domain=candidate.domain,
        seed=_source_seed(candidate),
        source_hash=_runtime_source_hash(
            train=train,
            validation=validation,
            clean_test=[],
        ),
        train=train,
        validation=validation,
        clean_test=[],
        metadata=metadata,
    )


def load_clean_runtime_view(
    path: Path | str,
    *,
    family: str | None = None,
) -> CleanEvolutionSplitManifest:
    """Load a legacy split or derive a screening-free candidate runtime view."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "rsebench.stable-split-candidate.v1":
        split = CleanEvolutionSplitManifest.model_validate(payload)
        declared_family = str(split.metadata.get("task_family") or "")
        if family is not None and declared_family and family != declared_family:
            raise ValueError(
                f"SkillLearn manifest family differs: {declared_family} != {family}"
            )
        return split
    candidate = StableSplitCandidate.model_validate(payload)
    if candidate.metadata.get("qualification_version") != "noise-screen-v1":
        raise ValueError("selection candidate is not noise-screen-v1")
    if candidate.benchmark == "skilllearnbench":
        return _skilllearn_view(candidate, family=family)
    if family is not None:
        raise ValueError("family selector is only valid for SkillLearn candidates")
    return _pool_view(candidate)


__all__ = ["load_clean_runtime_view"]
