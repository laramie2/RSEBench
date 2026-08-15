"""Build and verify portable resource locks from preregistered selection roots."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rsebench.hashing import sha256_file, sha256_tree
from rsebench.registry import load_registry
from rsebench.selection.contracts import ResourceLock, ResourceReference


BASELINE_METHODS = (
    "skilladaptor",
    "skilllearn_self_feedback",
    "skillopt",
)
_CHECKOUT_NAMES = {"skilllearn_self_feedback": "skilllearnbench"}


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _owned_file(root: Path, raw: Any) -> Path:
    locator = Path(str(raw))
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


def _portable_uris(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return set().union(*(_portable_uris(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_portable_uris(child) for child in value))
    if isinstance(value, str) and value.startswith(
        ("rsebench-data://", "rsebench-methods://")
    ):
        return {value}
    return set()


def _selection_documents(selection_root: Path) -> list[dict[str, Any]]:
    root = selection_root.resolve()
    index = _read_object(_owned_file(root, "manifest.json"))
    candidates = index.get("candidates")
    confirmations = index.get("confirmation")
    if not isinstance(candidates, dict) or not isinstance(confirmations, dict):
        raise ValueError("selection manifest lacks candidate/confirmation indexes")
    locators: list[Any] = []
    for rows in candidates.values():
        if not isinstance(rows, list):
            raise ValueError("selection candidate index must contain lists")
        locators.extend(rows)
    locators.extend(confirmations.values())
    return [_read_object(_owned_file(root, locator)) for locator in locators]


def _materialized_path(uri: str, *, data_root: Path, methods_root: Path) -> Path:
    if uri.startswith("rsebench-data://"):
        root = data_root.resolve()
        relative = uri.removeprefix("rsebench-data://")
    elif uri.startswith("rsebench-methods://"):
        root = methods_root.resolve()
        relative = uri.removeprefix("rsebench-methods://")
    else:
        raise ValueError(f"unsupported local resource URI: {uri}")
    parts = Path(relative).parts
    if not relative or ".." in parts or "." in parts:
        raise ValueError(f"unsafe portable resource URI: {uri}")
    candidate = root / relative
    if candidate.is_symlink() or any(
        parent.is_symlink() for parent in candidate.parents if parent != root.parent
    ):
        raise ValueError(f"portable resource traverses a symlink: {uri}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"portable resource escapes materialization root: {uri}") from exc
    if not resolved.exists():
        raise FileNotFoundError(f"portable resource is not materialized: {uri}")
    return resolved


def _path_hash(path: Path) -> str:
    return sha256_file(path) if path.is_file() else sha256_tree(path)


def _git_output(repository: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repository), *args],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"git materialization is unreadable: {repository}") from exc


def _git_tree_hash(repository: Path) -> str:
    names = [
        name
        for name in _git_output(
            repository,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ).splitlines()
        if name
    ]
    digest = hashlib.sha256()
    for name in sorted(names):
        path = repository / name
        if not path.is_file():
            raise ValueError(f"tracked git materialization is missing: {path}")
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _method_rows(methods_registry: Path) -> dict[str, dict[str, Any]]:
    rows = load_registry(methods_registry).get("methods")
    if not isinstance(rows, dict):
        raise ValueError("methods registry lacks methods")
    selected: dict[str, dict[str, Any]] = {}
    for baseline in BASELINE_METHODS:
        row = rows.get(baseline)
        if not isinstance(row, dict):
            raise ValueError(f"methods registry lacks baseline: {baseline}")
        selected[baseline] = row
    return selected


def _git_reference(
    baseline: str,
    row: Mapping[str, Any],
    *,
    methods_root: Path,
) -> ResourceReference:
    repository_url = str(row.get("repository") or "")
    revision = str(row.get("commit") or "")
    if not repository_url.startswith("https://"):
        raise ValueError(f"baseline repository is not HTTPS: {baseline}")
    repository = (methods_root / _CHECKOUT_NAMES.get(baseline, baseline)).resolve()
    actual_revision = _git_output(repository, "rev-parse", "HEAD")
    if actual_revision != revision:
        raise ValueError(f"git revision differs from registry: {baseline}")
    return ResourceReference(
        uri=f"git+{repository_url}@{revision}",
        kind="git",
        sha256=_git_tree_hash(repository),
        materialization=f"rsebench-methods://{baseline}",
    )


def _image_references(
    image_manifest: Path,
    *,
    required_task_ids: set[str],
) -> list[ResourceReference]:
    payload = _read_object(image_manifest)
    if payload.get("all_ready") is not True or not isinstance(payload.get("images"), list):
        raise ValueError("SkillLearn image manifest is not all_ready")
    task_to_context = payload.get("task_to_context_hash")
    if not isinstance(task_to_context, dict) or set(task_to_context) != required_task_ids:
        raise ValueError("SkillLearn image task mapping differs from selection tasks")
    resources: list[ResourceReference] = []
    covered: set[str] = set()
    for index, row in enumerate(payload["images"]):
        if not isinstance(row, dict):
            raise ValueError("SkillLearn image row must be an object")
        image_id = str(row.get("image_id") or "")
        if not image_id.startswith("sha256:"):
            raise ValueError("SkillLearn image is not digest pinned")
        digest = image_id.removeprefix("sha256:")
        context = str(row.get("context_hash") or f"image-{index}")
        task_ids = row.get("task_ids")
        if not isinstance(task_ids, list) or any(
            not isinstance(task_id, str) for task_id in task_ids
        ):
            raise ValueError("SkillLearn image task coverage is malformed")
        covered.update(task_ids)
        if any(task_to_context.get(task_id) != context for task_id in task_ids):
            raise ValueError("SkillLearn image context mapping differs from image row")
        safe_context = context if context.isalnum() else hashlib.sha256(context.encode()).hexdigest()
        resources.append(
            ResourceReference(
                uri=f"oci://rsebench.local/skilllearn/{safe_context}@sha256:{digest}",
                kind="external-image",
                sha256=digest,
                materialization=f"docker-image://sha256:{digest}",
                task_ids=sorted(task_ids),
            )
        )
    if covered != required_task_ids:
        raise ValueError("SkillLearn image coverage differs from selection tasks")
    return resources


def build_resource_lock(
    *,
    selection_root: Path,
    data_root: Path,
    methods_root: Path,
    methods_registry: Path,
    image_manifest: Path,
) -> ResourceLock:
    """Build a lock covering every selection URI, baseline pin, and image digest."""

    documents = _selection_documents(selection_root)
    uris = set().union(*(_portable_uris(document) for document in documents))
    resources: list[ResourceReference] = []
    for uri in sorted(uris):
        path = _materialized_path(
            uri, data_root=data_root, methods_root=methods_root
        )
        resources.append(
            ResourceReference(
                uri=uri,
                kind=(
                    "rsebench-data"
                    if uri.startswith("rsebench-data://")
                    else "rsebench-methods"
                ),
                sha256=_path_hash(path),
                materialization=uri,
            )
        )
    method_rows = _method_rows(methods_registry)
    resources.extend(
        _git_reference(
            baseline,
            method_rows[baseline],
            methods_root=methods_root.resolve(),
        )
        for baseline in BASELINE_METHODS
    )
    required_skill_ids = {
        str(task.get("task_id"))
        for document in documents
        if document.get("benchmark") == "skilllearnbench"
        for role in ("train", "validation", "qualification_test", "screening_test", "confirmation_test")
        for task in document.get(role, [])
        if isinstance(task, dict) and task.get("task_id")
    }
    resources.extend(
        _image_references(
            image_manifest,
            required_task_ids=required_skill_ids,
        )
    )
    return ResourceLock(resources=sorted(resources, key=lambda row: row.uri))


def validate_resource_lock_materializations(
    lock: ResourceLock,
    *,
    data_root: Path,
    methods_root: Path,
    methods_registry: Path,
) -> None:
    """Verify local hashes, baseline revisions, and OCI digest bindings."""

    method_rows = _method_rows(methods_registry)
    expected_git = {
        baseline: _git_reference(
            baseline,
            method_rows[baseline],
            methods_root=methods_root.resolve(),
        )
        for baseline in BASELINE_METHODS
    }
    for resource in lock.resources:
        if resource.kind in {"rsebench-data", "rsebench-methods"}:
            path = _materialized_path(
                resource.uri,
                data_root=data_root,
                methods_root=methods_root,
            )
            if _path_hash(path) != resource.sha256:
                raise ValueError(
                    f"materialization hash differs from lock: {resource.uri}"
                )
        elif resource.kind == "git":
            baseline = resource.materialization.removeprefix("rsebench-methods://")
            expected = expected_git.get(baseline)
            if expected is None:
                raise ValueError(f"unexpected baseline git pin: {baseline}")
            revision = resource.uri.rpartition("@")[2]
            actual_revision = _git_output(
                methods_root / _CHECKOUT_NAMES.get(baseline, baseline),
                "rev-parse",
                "HEAD",
            )
            if actual_revision != revision:
                raise ValueError(f"git revision differs from lock: {baseline}")
            if resource != expected:
                raise ValueError(f"git materialization differs from registry: {baseline}")


def write_resource_lock(path: Path, lock: ResourceLock) -> None:
    """Write one deterministic provider-free resource-lock document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(lock.model_dump_json(indent=2) + "\n", encoding="utf-8")


__all__ = [
    "BASELINE_METHODS",
    "build_resource_lock",
    "validate_resource_lock_materializations",
    "write_resource_lock",
]
