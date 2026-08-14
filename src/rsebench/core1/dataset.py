"""Frozen paired-split helpers shared by every Core-1 domain builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rsebench.contracts import (
    Channel,
    GeneratorMode,
    Mechanism,
    NoiseManifest,
    NoiseTiming,
    Severity,
    SeverityLevel,
    TaskManifest,
)
from rsebench.core1.materialize import Core1NoiseProfile
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.evolution.contracts import EvolutionSplitManifest, EvolutionTaskPair


_STAGE_SEMANTICS = {
    "N1": (Channel.task_communication, Mechanism.distortion),
    "N2": (Channel.evidence_artifact, Mechanism.duplication_staleness),
    "N3": (Channel.interaction_observation, Mechanism.omission),
    "N4": (Channel.feedback_selection, Mechanism.distortion),
}
_REFERENCE_ROOTS = {
    "rsebench-project": "project_root",
    "rsebench-data": "data_root",
    "rsebench-methods": "methods_root",
}
_LOCATOR_KEYS = {
    "artifact_path",
    "gold_workbook_path",
    "official_instance_path",
    "retrieval_fixture",
    "static_noise_path",
}


def _hash_metadata(value: Any, *, key: str | None = None) -> Any:
    if key in _LOCATOR_KEYS or (key is not None and key.endswith("_path")):
        return None
    if isinstance(value, dict):
        return {
            child_key: _hash_metadata(child, key=child_key)
            for child_key, child in value.items()
            if child_key not in _LOCATOR_KEYS and not child_key.endswith("_path")
        }
    if isinstance(value, list):
        return [_hash_metadata(child) for child in value]
    return value


def rehash_task(
    task: TaskManifest, *, artifact_hash: str | None = None
) -> TaskManifest:
    """Return a task whose hash covers its immutable public payload.

    Artifact bytes are supplied explicitly so callers can hash files or trees
    with the representation appropriate to the benchmark. Paths remain in the
    payload for replay, while ``artifact_hash`` makes byte changes observable.
    """

    payload = task.model_dump(
        mode="json", exclude={"source_hash", "artifact_path"}
    )
    payload["metadata"] = _hash_metadata(payload.get("metadata", {}))
    if artifact_hash is not None:
        payload["artifact_hash"] = artifact_hash
    return task.model_copy(update={"source_hash": canonical_hash(payload)}, deep=True)


def _root_mapping(
    *, project_root: Path | str, data_root: Path | str, methods_root: Path | str
) -> dict[str, Path]:
    return {
        "rsebench-project": Path(project_root).resolve(),
        "rsebench-data": Path(data_root).resolve(),
        "rsebench-methods": Path(methods_root).resolve(),
    }


def _portable_reference(value: Any, roots: dict[str, Path]) -> Any:
    if isinstance(value, dict):
        return {key: _portable_reference(child, roots) for key, child in value.items()}
    if isinstance(value, list):
        return [_portable_reference(child, roots) for child in value]
    if not isinstance(value, str) or not Path(value).is_absolute():
        return value
    path = Path(value).resolve()
    # Roots may be nested in a canonical checkout (for example ``data`` and
    # ``methods/external`` live below the project root). Prefer the most
    # specific declared root so portable manifests keep their semantic
    # locator instead of collapsing everything to ``rsebench-project``.
    ordered_roots = sorted(
        roots.items(), key=lambda item: len(item[1].parts), reverse=True
    )
    for scheme, root in ordered_roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        return f"{scheme}://{relative.as_posix()}"
    raise ValueError(f"Core-1 path is outside declared portable roots: {path}")


def _resolved_reference(value: Any, roots: dict[str, Path]) -> Any:
    if isinstance(value, dict):
        return {key: _resolved_reference(child, roots) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolved_reference(child, roots) for child in value]
    if not isinstance(value, str):
        return value
    for scheme, root in roots.items():
        prefix = f"{scheme}://"
        if not value.startswith(prefix):
            continue
        relative = value[len(prefix) :]
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"path reference escapes {scheme}: {value}") from exc
        return str(candidate)
    return value


def _map_task_paths(
    task: TaskManifest, roots: dict[str, Path], *, portable: bool
) -> TaskManifest:
    mapper = _portable_reference if portable else _resolved_reference
    return task.model_copy(
        update={
            "artifact_path": mapper(task.artifact_path, roots),
            "metadata": mapper(task.metadata, roots),
        },
        deep=True,
    )


def _map_split_paths(
    split: EvolutionSplitManifest,
    *,
    roots: dict[str, Path],
    portable: bool,
) -> EvolutionSplitManifest:
    pairs = []
    for pair in split.train + split.validation:
        pairs.append(
            pair.model_copy(
                update={
                    "clean": _map_task_paths(pair.clean, roots, portable=portable),
                    "noisy": _map_task_paths(pair.noisy, roots, portable=portable),
                    "noise": pair.noise.model_copy(
                        update={
                            "metadata": (
                                _portable_reference(pair.noise.metadata, roots)
                                if portable
                                else _resolved_reference(pair.noise.metadata, roots)
                            )
                        },
                        deep=True,
                    ),
                },
                deep=True,
            )
        )
    train = pairs[: len(split.train)]
    validation = pairs[len(split.train) :]
    clean_test = [
        _map_task_paths(task, roots, portable=portable)
        for task in split.clean_test
    ]
    updated = split.model_copy(
        update={"train": train, "validation": validation, "clean_test": clean_test},
        deep=True,
    )
    if portable:
        stage = ""
        if train or validation:
            stage = (train + validation)[0].noise.metadata.get("stage", "")
        payload = {
            "benchmark": updated.benchmark,
            "domain": updated.domain,
            "seed": updated.seed,
            "stage": stage,
            "train": [pair.model_dump(mode="json") for pair in train],
            "validation": [pair.model_dump(mode="json") for pair in validation],
            "clean_test": [task.model_dump(mode="json") for task in clean_test],
        }
        updated = updated.model_copy(update={"source_hash": canonical_hash(payload)})
    return updated


def make_split_paths_portable(
    split: EvolutionSplitManifest,
    *,
    project_root: Path | str,
    data_root: Path | str,
    methods_root: Path | str,
) -> EvolutionSplitManifest:
    """Encode machine paths as release-stable root references."""

    return _map_split_paths(
        split,
        roots=_root_mapping(
            project_root=project_root,
            data_root=data_root,
            methods_root=methods_root,
        ),
        portable=True,
    )


def resolve_split_paths(
    split: EvolutionSplitManifest,
    *,
    project_root: Path | str,
    data_root: Path | str,
    methods_root: Path | str,
) -> EvolutionSplitManifest:
    """Resolve release references for one local baseline execution."""

    return _map_split_paths(
        split,
        roots=_root_mapping(
            project_root=project_root,
            data_root=data_root,
            methods_root=methods_root,
        ),
        portable=False,
    )


def _map_clean_split_paths(
    split: CleanEvolutionSplitManifest,
    *,
    roots: dict[str, Path],
    portable: bool,
) -> CleanEvolutionSplitManifest:
    train = [
        _map_task_paths(task, roots, portable=portable) for task in split.train
    ]
    validation = [
        _map_task_paths(task, roots, portable=portable)
        for task in split.validation
    ]
    clean_test = [
        _map_task_paths(task, roots, portable=portable)
        for task in split.clean_test
    ]
    updated = split.model_copy(
        update={"train": train, "validation": validation, "clean_test": clean_test},
        deep=True,
    )
    if portable:
        payload = {
            "benchmark": updated.benchmark,
            "domain": updated.domain,
            "seed": updated.seed,
            "train": [task.model_dump(mode="json") for task in train],
            "validation": [task.model_dump(mode="json") for task in validation],
            "clean_test": [task.model_dump(mode="json") for task in clean_test],
            "metadata": updated.metadata,
        }
        updated = updated.model_copy(update={"source_hash": canonical_hash(payload)})
    return updated


def make_clean_split_paths_portable(
    split: CleanEvolutionSplitManifest,
    *,
    project_root: Path | str,
    data_root: Path | str,
    methods_root: Path | str,
) -> CleanEvolutionSplitManifest:
    """Encode clean-manifest paths as release-stable root references."""

    return _map_clean_split_paths(
        split,
        roots=_root_mapping(
            project_root=project_root,
            data_root=data_root,
            methods_root=methods_root,
        ),
        portable=True,
    )


def resolve_clean_split_paths(
    split: CleanEvolutionSplitManifest,
    *,
    project_root: Path | str,
    data_root: Path | str,
    methods_root: Path | str,
) -> CleanEvolutionSplitManifest:
    """Resolve clean-manifest root references for one local execution."""

    return _map_clean_split_paths(
        split,
        roots=_root_mapping(
            project_root=project_root,
            data_root=data_root,
            methods_root=methods_root,
        ),
        portable=False,
    )


def build_core1_pair(
    *,
    clean: TaskManifest,
    noisy: TaskManifest,
    profile: Core1NoiseProfile,
    metadata: dict[str, Any] | None = None,
) -> EvolutionTaskPair:
    stage = profile.stage.value
    channel, mechanism = _STAGE_SEMANTICS[stage]
    runtime = profile.form == "runtime"
    noise = NoiseManifest(
        noise_id=f"core1:{profile.benchmark}:{stage}:{clean.task_id}",
        task_id=clean.task_id,
        channel=channel,
        mechanism=mechanism,
        operator=profile.operator,
        domain=profile.domain,
        benchmark=profile.benchmark,
        severity=Severity(level=SeverityLevel.medium, budget=profile.budget),
        seed=profile.seed,
        clean_hash=clean.source_hash,
        noisy_hash=noisy.source_hash,
        generator_mode=GeneratorMode(profile.mode),
        timing=NoiseTiming.evolution,
        template_version=profile.operator_version,
        metadata={
            "stage": stage,
            "materialization": "runtime_hook" if runtime else "frozen_pair",
            "runtime_spec": (
                f"benchmark/core1/runtime/{profile.benchmark}/{stage}.json"
                if runtime
                else None
            ),
            **(metadata or {}),
        },
    )
    return EvolutionTaskPair(
        pair_id=f"{profile.benchmark}:{stage}:{clean.task_id}",
        task_id=clean.task_id,
        clean=clean,
        noisy=noisy,
        noise=noise,
    )


def build_core1_split(
    *,
    profile: Core1NoiseProfile,
    train: list[EvolutionTaskPair],
    validation: list[EvolutionTaskPair],
    clean_test: list[TaskManifest],
) -> EvolutionSplitManifest:
    payload = {
        "benchmark": profile.benchmark,
        "domain": profile.domain,
        "seed": profile.seed,
        "stage": profile.stage.value,
        "train": [pair.model_dump(mode="json") for pair in train],
        "validation": [pair.model_dump(mode="json") for pair in validation],
        "clean_test": [task.model_dump(mode="json") for task in clean_test],
    }
    return EvolutionSplitManifest(
        benchmark=profile.benchmark,
        domain=profile.domain,
        seed=profile.seed,
        source_hash=canonical_hash(payload),
        train=train,
        validation=validation,
        clean_test=clean_test,
    )
