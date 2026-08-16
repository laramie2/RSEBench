#!/usr/bin/env python3
"""Prebuild and audit Docker images for clean SkillLearn qualification."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SHARED_ROOT = (
    PROJECT_ROOT.parents[1] if ".worktrees" in PROJECT_ROOT.parts else PROJECT_ROOT
)

from rsebench.core1.dataset import (  # noqa: E402
    resolve_candidate_paths,
    resolve_clean_split_paths,
    resolve_confirmation_paths,
)
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
)
from rsebench.evolution.skilllearn_executor import (  # noqa: E402
    DockerSkillLearnBackend,
)
from rsebench.hashing import sha256_file, sha256_tree  # noqa: E402
from rsebench.selection.contracts import (  # noqa: E402
    ConfirmationSplit,
    StableSplitCandidate,
)
from rsebench.selection.splits import (  # noqa: E402
    CONFIRMATION_SKILLLEARN_FAMILIES,
    SCREENING_SKILLLEARN_FAMILIES,
)
from scripts.baselines.common_env import (  # noqa: E402,F401
    combined_method_env,
    methods_root,
)
from scripts.build_clean_skilllearn_qualification import FAMILIES  # noqa: E402


DEFAULT_MANIFEST_ROOT = (
    PROJECT_ROOT / "benchmark/validation/clean_qualification_v1/skilllearnbench"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs/preflight/clean-qualification-v1/skilllearn/image_manifest.json"
)
OFFLINE_VERIFIER_PACKAGES = (
    "pytest==8.4.1",
    "pytest-json-ctrf==0.3.5",
)
OFFLINE_VERIFIER_WHEEL_REQUIREMENTS = (
    *OFFLINE_VERIFIER_PACKAGES,
    "exceptiongroup==1.3.1",
    "tomli==2.0.1",
    "typing-extensions==4.15.0",
)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prepare_verifier_wheelhouse(
    wheelhouse: Path,
    *,
    require_existing: bool = False,
) -> dict[str, Any]:
    """Download or audit the pinned verifier wheelhouse."""

    root = Path(wheelhouse).resolve()
    root.mkdir(parents=True, exist_ok=True)
    existing = sorted(path for path in root.iterdir() if path.is_file())
    if require_existing:
        if not existing:
            raise FileNotFoundError(
                f"SkillLearn verifier wheelhouse is empty: {root}"
            )
    else:
        if existing:
            raise FileExistsError(
                "SkillLearn verifier wheelhouse must be empty before download: "
                f"{root}"
            )
        downloaded = subprocess.run(
            [
                "pip",
                "download",
                "--dest",
                str(root),
                "--only-binary=:all:",
                *OFFLINE_VERIFIER_WHEEL_REQUIREMENTS,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if downloaded.returncode != 0:
            raise RuntimeError(
                "SkillLearn verifier wheel download failed: "
                f"{(downloaded.stderr or downloaded.stdout)[-4000:]}"
            )
    wheels = sorted(path for path in root.iterdir() if path.is_file())
    if not wheels:
        raise RuntimeError("SkillLearn verifier wheel download produced no files")
    return {
        "mode": "offline_pytest",
        "packages": list(OFFLINE_VERIFIER_PACKAGES),
        "wheel_requirements": list(OFFLINE_VERIFIER_WHEEL_REQUIREMENTS),
        "wheelhouse_hash": sha256_tree(root),
        "wheels": [
            {"name": path.name, "sha256": sha256_file(path)} for path in wheels
        ],
    }


def _verifier_payload(
    *,
    output: Path,
    verifier_wheelhouse: Path | None,
    require_existing: bool,
) -> dict[str, Any]:
    if verifier_wheelhouse is None:
        return {}
    root = Path(verifier_wheelhouse).resolve()
    try:
        locator = root.relative_to(Path(output).resolve().parent).as_posix()
    except ValueError as exc:
        raise ValueError(
            "SkillLearn verifier wheelhouse must be below the image manifest directory"
        ) from exc
    verifier = prepare_verifier_wheelhouse(
        root,
        require_existing=require_existing,
    )
    return {"verifier": {**verifier, "wheelhouse": locator}}


def _ordered_manifests(root: Path) -> list[Path]:
    by_name = {path.stem: path for path in root.glob("*.json")}
    ordered = [by_name.pop(family) for family in FAMILIES if family in by_name]
    ordered.extend(by_name[name] for name in sorted(by_name))
    return ordered


def _owned_file(root: Path, raw: str) -> Path:
    locator = Path(raw)
    if locator.is_absolute() or ".." in locator.parts:
        raise ValueError(f"selection locator must be root-relative: {raw}")
    path = root / locator
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError(f"selection locator traverses a symlink: {raw}")
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"selection locator escapes root: {raw}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"selection artifact is missing: {resolved}")
    return resolved


def _prebuild_tasks(
    *,
    tasks: list[Any],
    qualification_version: str,
    output: Path,
    require_existing: bool,
    record_root: Path | None,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("SkillLearn task IDs are duplicated across prebuild roles")
    records = Path(record_root) if record_root is not None else output.parent / "records"
    backend = DockerSkillLearnBackend(
        client=object(),
        require_prebuilt=require_existing,
    )
    payload: dict[str, Any] = {
        "schema_version": "rsebench.skilllearn-image-manifest.v1",
        "qualification_version": qualification_version,
        "require_existing": require_existing,
        "provider_calls": 0,
        "images": [],
        "task_to_context_hash": {},
        "failures": [],
        "all_ready": False,
        **(extra_payload or {}),
    }
    images: dict[str, dict[str, Any]] = {}
    for task in tasks:
        try:
            record = backend.prepare(
                task,
                records / task.task_id,
            )
        except Exception as exc:
            payload["failures"].append(
                {
                    "task_id": task.task_id,
                    "status": "failed",
                    "stderr": str(exc),
                }
            )
            _write(output, payload)
            raise
        payload["task_to_context_hash"][task.task_id] = record.context_hash
        candidate = record.model_dump(mode="json")
        candidate["task_ids"] = [task.task_id]
        existing = images.get(record.context_hash)
        if existing is None:
            images[record.context_hash] = candidate
        else:
            if (
                existing["image_tag"] != record.image_tag
                or existing["image_id"] != record.image_id
            ):
                raise RuntimeError(
                    f"conflicting image identity for context {record.context_hash}"
                )
            existing["task_ids"].append(task.task_id)
    payload["images"] = [images[key] for key in sorted(images)]
    payload["all_ready"] = not payload["failures"]
    _write(output, payload)
    return payload


def prebuild_images(
    *,
    manifest_root: Path,
    output: Path,
    require_existing: bool = False,
    record_root: Path | None = None,
    verifier_wheelhouse: Path | None = None,
) -> dict[str, Any]:
    external_methods = methods_root()
    manifest_paths = _ordered_manifests(manifest_root)
    versions = {
        str(
            CleanEvolutionSplitManifest.model_validate_json(
                path.read_text(encoding="utf-8")
            ).metadata.get("qualification_version")
            or "clean-qualification-v1"
        )
        for path in manifest_paths
    }
    if len(versions) != 1:
        raise ValueError("SkillLearn image prebuild cannot mix qualification versions")
    qualification_version = versions.pop()
    tasks = []
    for manifest_path in manifest_paths:
        portable = CleanEvolutionSplitManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        split = resolve_clean_split_paths(
            portable,
            project_root=PROJECT_ROOT,
            data_root=SHARED_ROOT / "data",
            methods_root=external_methods,
        )
        tasks.extend([*split.train, *split.validation, *split.clean_test])
    return _prebuild_tasks(
        tasks=tasks,
        qualification_version=qualification_version,
        output=output,
        require_existing=require_existing,
        record_root=record_root,
        extra_payload=_verifier_payload(
            output=output,
            verifier_wheelhouse=verifier_wheelhouse,
            require_existing=require_existing,
        ),
    )


def prebuild_selection_images(
    *,
    selection_root: Path,
    output: Path,
    data_root: Path | None = None,
    methods_root_path: Path | None = None,
    require_existing: bool = False,
    record_root: Path | None = None,
    verifier_wheelhouse: Path | None = None,
) -> dict[str, Any]:
    """Prebuild every fixed SkillLearn screening and confirmation task."""

    root = Path(selection_root).resolve()
    index = json.loads(_owned_file(root, "manifest.json").read_text(encoding="utf-8"))
    candidate_index = index.get("candidates", {}).get("skilllearnbench")
    confirmation_locator = index.get("confirmation", {}).get("skilllearnbench")
    if not isinstance(candidate_index, list) or len(candidate_index) != 1:
        raise ValueError("selection root requires one aggregate SkillLearn candidate")
    if not isinstance(confirmation_locator, str):
        raise ValueError("selection root requires one aggregate SkillLearn confirmation")
    candidate = StableSplitCandidate.model_validate_json(
        _owned_file(root, str(candidate_index[0])).read_text(encoding="utf-8")
    )
    confirmation = ConfirmationSplit.model_validate_json(
        _owned_file(root, confirmation_locator).read_text(encoding="utf-8")
    )
    screening_families = list(candidate.metadata.get("families") or [])
    confirmation_families = list(confirmation.metadata.get("families") or [])
    if screening_families != list(SCREENING_SKILLLEARN_FAMILIES):
        raise ValueError("SkillLearn aggregate candidate has substituted families")
    if confirmation_families != list(CONFIRMATION_SKILLLEARN_FAMILIES):
        raise ValueError("SkillLearn aggregate confirmation has substituted families")
    candidate_tasks = [
        *candidate.train,
        *candidate.validation,
        *candidate.qualification_test,
        *candidate.screening_test,
    ]
    confirmation_tasks = [
        *confirmation.train,
        *confirmation.validation,
        *confirmation.confirmation_test,
    ]
    if {
        task.metadata.get("task_family") for task in candidate_tasks
    } != set(SCREENING_SKILLLEARN_FAMILIES):
        raise ValueError("SkillLearn aggregate candidate task families differ")
    if {
        task.metadata.get("task_family") for task in confirmation_tasks
    } != set(CONFIRMATION_SKILLLEARN_FAMILIES):
        raise ValueError("SkillLearn aggregate confirmation task families differ")
    local_methods = (
        Path(methods_root_path).resolve()
        if methods_root_path is not None
        else methods_root()
    )
    local_data = Path(data_root or SHARED_ROOT / "data").resolve()
    resolved_candidate = resolve_candidate_paths(
        candidate,
        project_root=PROJECT_ROOT,
        data_root=local_data,
        methods_root=local_methods,
    )
    resolved_confirmation = resolve_confirmation_paths(
        confirmation,
        project_root=PROJECT_ROOT,
        data_root=local_data,
        methods_root=local_methods,
    )
    tasks = [
        *resolved_candidate.train,
        *resolved_candidate.validation,
        *resolved_candidate.qualification_test,
        *resolved_candidate.screening_test,
        *resolved_confirmation.train,
        *resolved_confirmation.validation,
        *resolved_confirmation.confirmation_test,
    ]
    return _prebuild_tasks(
        tasks=tasks,
        qualification_version="noise-screen-v1",
        output=output,
        require_existing=require_existing,
        record_root=record_root,
        extra_payload={
            "families": [*screening_families, *confirmation_families],
            "selection_hashes": {
                "candidate": candidate.selection_hash,
                "confirmation": confirmation.selection_hash,
            },
            **_verifier_payload(
                output=output,
                verifier_wheelhouse=verifier_wheelhouse,
                require_existing=require_existing,
            ),
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--manifest-root", type=Path)
    source.add_argument("--selection-root", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-existing", action="store_true")
    parser.add_argument("--record-root", type=Path)
    parser.add_argument("--verifier-wheelhouse", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.selection_root is not None:
        prebuild_selection_images(
            selection_root=args.selection_root,
            output=args.output,
            require_existing=args.require_existing,
            record_root=args.record_root,
            verifier_wheelhouse=args.verifier_wheelhouse,
        )
    else:
        prebuild_images(
            manifest_root=args.manifest_root or DEFAULT_MANIFEST_ROOT,
            output=args.output,
            require_existing=args.require_existing,
            record_root=args.record_root,
            verifier_wheelhouse=args.verifier_wheelhouse,
        )
    print("provider_calls=0")
    print(args.output)


if __name__ == "__main__":
    main()
