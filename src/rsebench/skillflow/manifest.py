"""Build and verify fixed-order SkillFlow family manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rsebench.evidence import canonical_hash
from rsebench.hashing import sha256_file, sha256_tree
from rsebench.skillflow.contracts import (
    SkillFlowCleanConfig,
    SkillFlowFamilyManifest,
    SkillFlowInputManifest,
    SkillFlowTaskIdentity,
)


_REQUIRED_FILES = ("task.toml", "instruction.md")
_REQUIRED_DIRS = ("environment", "solution", "tests")


def _contained(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"SkillFlow path escapes data root: {candidate}") from exc
    return resolved


def _ranking(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload or any(
        not isinstance(item, str) or not item.strip() for item in payload
    ):
        raise ValueError(f"invalid SkillFlow ranking: {path}")
    names = [item.strip() for item in payload]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate SkillFlow ranking entries: {path}")
    if any(Path(name).name != name or name in {".", ".."} for name in names):
        raise ValueError(f"unsafe SkillFlow ranking entry: {path}")
    return names


def _valid_task(task: Path) -> bool:
    return all((task / name).is_file() for name in _REQUIRED_FILES) and all(
        (task / name).is_dir() for name in _REQUIRED_DIRS
    )


def _family_components(
    family: Path,
) -> tuple[Path, list[str], dict[str, Path], set[str]]:
    ranking_path = family / "ALL_TASK_DIFFICULTY_RANKING.json"
    if not ranking_path.is_file():
        raise FileNotFoundError(f"SkillFlow ranking is missing: {ranking_path}")
    ranked = _ranking(ranking_path)
    task_dirs = {
        item.name: item
        for item in family.iterdir()
        if item.is_dir() and not item.name.startswith(".") and item.name != "jobs"
    }
    valid_names = {name for name, task in task_dirs.items() if _valid_task(task)}
    return ranking_path, ranked, task_dirs, valid_names


def build_family_manifest(
    family_root: Path | str,
    *,
    data_root: Path | str,
) -> SkillFlowFamilyManifest:
    root = Path(data_root).resolve()
    family = _contained(root, Path(family_root))
    if not family.is_dir():
        raise FileNotFoundError(f"SkillFlow family is missing: {family}")
    ranking_path, ranked, task_dirs, valid_names = _family_components(family)
    if set(ranked) != valid_names or set(task_dirs) != valid_names:
        raise ValueError(
            f"ranking differs from valid tasks for {family.name}: "
            f"ranking={sorted(ranked)}, valid={sorted(valid_names)}, "
            f"directories={sorted(task_dirs)}"
        )
    tasks = [
        SkillFlowTaskIdentity(
            task_id=name,
            order=index,
            relative_path=(task_dirs[name].relative_to(root)).as_posix(),
            task_hash=sha256_tree(task_dirs[name]),
        )
        for index, name in enumerate(ranked, start=1)
    ]
    return SkillFlowFamilyManifest(
        family=family.name,
        status="ready",
        ranking_hash=sha256_file(ranking_path),
        ranked_task_ids=ranked,
        tasks=tasks,
        invalid_reasons=[],
    )


def audit_family_manifest(
    family_root: Path | str,
    *,
    data_root: Path | str,
) -> SkillFlowFamilyManifest:
    root = Path(data_root).resolve()
    family = _contained(root, Path(family_root))
    if not family.is_dir():
        raise FileNotFoundError(f"SkillFlow family is missing: {family}")
    ranking_path, ranked, task_dirs, valid_names = _family_components(family)
    missing = [name for name in ranked if name not in valid_names]
    unranked = sorted(valid_names - set(ranked))
    invalid_directories = sorted(set(task_dirs) - valid_names)
    reasons = [f"ranking_missing_task:{name}" for name in missing]
    reasons.extend(f"unranked_task:{name}" for name in unranked)
    reasons.extend(f"invalid_task_directory:{name}" for name in invalid_directories)
    if not reasons:
        return build_family_manifest(family, data_root=root)
    ordered_present = [name for name in ranked if name in valid_names]
    ordered_present.extend(name for name in unranked if name not in ordered_present)
    ranking_positions = {name: index for index, name in enumerate(ranked, start=1)}
    tasks = [
        SkillFlowTaskIdentity(
            task_id=name,
            order=(
                ranking_positions[name]
                if name in ranking_positions
                else len(ranked) + unranked.index(name) + 1
            ),
            relative_path=task_dirs[name].relative_to(root).as_posix(),
            task_hash=sha256_tree(task_dirs[name]),
        )
        for name in ordered_present
    ]
    return SkillFlowFamilyManifest(
        family=family.name,
        status="invalid",
        ranking_hash=sha256_file(ranking_path),
        ranked_task_ids=ranked,
        tasks=tasks,
        invalid_reasons=reasons,
    )


def build_input_manifest(
    *,
    data_root: Path | str,
    config: SkillFlowCleanConfig,
) -> SkillFlowInputManifest:
    root = Path(data_root).resolve()
    families = [
        audit_family_manifest(root / family, data_root=root)
        for family in [*config.batch_a, *config.batch_b]
    ]
    invalid_sizes = {
        family.family: len(family.tasks)
        for family in families
        if family.status == "ready" and len(family.tasks) not in {8, 9}
    }
    if invalid_sizes:
        raise ValueError(f"SkillFlow candidate family size must be 8 or 9: {invalid_sizes}")
    return SkillFlowInputManifest(
        schema_version="rsebench.skillflow-input.v1",
        benchmark=config.benchmark,
        baseline=config.baseline,
        upstream_revision=config.upstream_revision,
        qualification_contract=config.qualification_contract,
        config_hash=canonical_hash(config),
        runtime=config.runtime,
        qualification=config.qualification,
        batch_a=list(config.batch_a),
        batch_b=list(config.batch_b),
        replicates=list(config.replicates),
        families=families,
        provider_calls=0,
    )


def verify_input_manifest(
    manifest: SkillFlowInputManifest | dict[str, Any],
    *,
    data_root: Path | str,
) -> SkillFlowInputManifest:
    expected = (
        manifest
        if isinstance(manifest, SkillFlowInputManifest)
        else SkillFlowInputManifest.model_validate(manifest)
    )
    by_family = {family.family: family for family in expected.families}
    root = Path(data_root).resolve()
    for family_name, frozen in by_family.items():
        actual = audit_family_manifest(root / family_name, data_root=root)
        if actual.ranking_hash != frozen.ranking_hash:
            raise RuntimeError(f"ranking hash differs for SkillFlow family: {family_name}")
        actual_tasks = {task.task_id: task for task in actual.tasks}
        for task in frozen.tasks:
            observed = actual_tasks.get(task.task_id)
            if observed is None or observed.task_hash != task.task_hash:
                raise RuntimeError(
                    f"task hash differs for SkillFlow task: {family_name}/{task.task_id}"
                )
        if actual != frozen:
            raise RuntimeError(f"SkillFlow family manifest differs: {family_name}")
    return expected


__all__ = [
    "audit_family_manifest",
    "build_family_manifest",
    "build_input_manifest",
    "verify_input_manifest",
]
