"""Portable, content-addressed releases for stable validation splits."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.selection.contracts import (
    CandidateDecision,
    ConfirmationSeal,
    ConfirmationSplit,
    ExposureRegistry,
    ResourceLock,
    SelectionReleaseManifest,
    StableSplitCandidate,
)


EXPECTED_DOMAINS = frozenset(
    {
        "spreadsheetbench_verified",
        "officeqa_full",
        "webshop",
        "skilllearnbench",
    }
)
EXPECTED_BASELINES = frozenset(
    {"skillopt", "skilladaptor", "skilllearn_self_feedback"}
)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_EMBEDDED_ABSOLUTE = re.compile(
    r"(?:^|\s)/(?:home|Users|workspace|workspaces|mnt|tmp|var|opt|root)(?:/|\b)"
)
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{12,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
)
_CREDENTIAL_NAMES = frozenset(
    {
        "deepseek_api_key",
        "openai_api_key",
        "anthropic_api_key",
        "azure_openai_api_key",
        "aws_secret_access_key",
        "api_key",
        "access_token",
        "client_secret",
        "password",
    }
)
_UNRESOLVED_MARKERS = (
    "file://",
    "unresolved://",
    "${",
    "<replace-me>",
    "replace_me",
    "todo://",
)


class FrozenSelectionRelease(StrictModel):
    """The immutable result of one selection release write."""

    path: Path
    release_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_hashes: dict[str, str]


class SelectionReleaseInput(StrictModel):
    """Strict JSON boundary used by the provider-free script and CLI."""

    candidates: dict[str, StableSplitCandidate]
    confirmations: dict[str, ConfirmationSplit]
    decisions: dict[str, CandidateDecision]
    domain_statuses: dict[str, str]
    exposure_registry: ExposureRegistry
    confirmation_seal: ConfirmationSeal
    resource_lock: ResourceLock
    baseline_fingerprints: dict[str, str]

    @model_validator(mode="after")
    def exact_release_keys(self) -> "SelectionReleaseInput":
        for field_name in (
            "candidates",
            "confirmations",
            "decisions",
            "domain_statuses",
        ):
            if set(getattr(self, field_name)) != EXPECTED_DOMAINS:
                raise ValueError(f"{field_name} requires exactly the four registered domains")
        return self


def _canonical_json_bytes(payload: Any) -> bytes:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _task_ids(tasks: Sequence[TaskManifest]) -> set[str]:
    return {task.task_id for task in tasks}


def validate_cross_release_disjointness(
    candidates: Mapping[str, StableSplitCandidate],
    confirmations: Mapping[str, ConfirmationSplit],
) -> None:
    """Raise when any benchmark reuses a screening-side confirmation task."""

    if set(candidates) != EXPECTED_DOMAINS or set(confirmations) != EXPECTED_DOMAINS:
        raise ValueError("cross-release validation requires exactly four domains")
    for benchmark in sorted(EXPECTED_DOMAINS):
        candidate = candidates[benchmark]
        confirmation = confirmations[benchmark]
        if candidate.benchmark != benchmark or confirmation.benchmark != benchmark:
            raise ValueError(f"release mapping key differs from benchmark: {benchmark}")
        if candidate.domain != confirmation.domain:
            raise ValueError(f"screening and confirmation domain differs: {benchmark}")
        screening_ids = _task_ids(
            [
                *candidate.train,
                *candidate.validation,
                *candidate.qualification_test,
                *candidate.screening_test,
            ]
        )
        confirmation_ids = _task_ids(
            [
                *confirmation.train,
                *confirmation.validation,
                *confirmation.confirmation_test,
            ]
        )
        overlap = screening_ids & confirmation_ids
        if overlap:
            raise ValueError(
                "screening and confirmation task IDs must be disjoint: "
                f"{benchmark}: {sorted(overlap)}"
            )


def _expected_confirmation_seal(
    confirmations: Mapping[str, ConfirmationSplit],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    split_hashes: dict[str, str] = {}
    task_ids: dict[str, list[str]] = {}
    for benchmark in sorted(confirmations):
        confirmation = confirmations[benchmark]
        for role in ("train", "validation", "confirmation_test"):
            tasks = list(getattr(confirmation, role))
            key = f"{benchmark}:{role}"
            split_hashes[key] = canonical_hash(
                [task.model_dump(mode="json") for task in tasks]
            )
            task_ids[key] = [task.task_id for task in tasks]
    return split_hashes, task_ids


def _validate_release_inputs(
    *,
    candidates: Mapping[str, StableSplitCandidate],
    confirmations: Mapping[str, ConfirmationSplit],
    decisions: Mapping[str, CandidateDecision],
    domain_statuses: Mapping[str, str],
    exposure_registry: ExposureRegistry,
    confirmation_seal: ConfirmationSeal,
    resource_lock: ResourceLock,
    baseline_fingerprints: Mapping[str, str],
) -> None:
    named_mappings = {
        "candidates": candidates,
        "confirmations": confirmations,
        "decisions": decisions,
        "domain_statuses": domain_statuses,
    }
    for name, values in named_mappings.items():
        if set(values) != EXPECTED_DOMAINS:
            raise ValueError(f"{name} requires exactly the four registered domains")
    if any(
        value != "clean_generalization_ready"
        for value in domain_statuses.values()
    ):
        raise ValueError("all domains must be clean_generalization_ready")
    if set(baseline_fingerprints) != EXPECTED_BASELINES:
        raise ValueError("release requires exactly the three registered baselines")
    for baseline, fingerprint in baseline_fingerprints.items():
        if not _HASH_PATTERN.fullmatch(fingerprint):
            raise ValueError(f"baseline fingerprint is not SHA-256: {baseline}")

    validate_cross_release_disjointness(candidates, confirmations)

    expected_registry_hash = canonical_hash(
        [record.model_dump(mode="json") for record in exposure_registry.records]
    )
    if exposure_registry.registry_hash != expected_registry_hash:
        raise ValueError("exposure registry hash differs from its records")
    if not confirmation_seal.created_before_screening:
        raise ValueError("confirmation split was not sealed before screening")
    if confirmation_seal.exposure_registry_hash != exposure_registry.registry_hash:
        raise ValueError("confirmation seal differs from the exposure registry")
    expected_split_hashes, expected_task_ids = _expected_confirmation_seal(
        confirmations
    )
    if dict(confirmation_seal.split_hashes) != expected_split_hashes:
        raise ValueError("confirmation seal split hashes differ from confirmations")
    if {
        key: list(values) for key, values in confirmation_seal.task_ids.items()
    } != expected_task_ids:
        raise ValueError("confirmation seal task IDs differ from confirmations")

    for benchmark in sorted(EXPECTED_DOMAINS):
        candidate = candidates[benchmark]
        confirmation = confirmations[benchmark]
        decision = decisions[benchmark]
        if candidate.metadata.get("selection_version") != "noise-screen-v1":
            raise ValueError(f"candidate is not noise-screen-v1: {benchmark}")
        if confirmation.metadata.get("selection_version") != "noise-screen-v1":
            raise ValueError(f"confirmation is not noise-screen-v1: {benchmark}")
        if decision.candidate_index != candidate.candidate_index:
            raise ValueError(f"decision candidate index differs: {benchmark}")
        if (
            not decision.passed
            or decision.next_action != "freeze_candidate"
            or decision.execution_coverage != 1.0
            or decision.noise_applicability != 1.0
        ):
            raise ValueError(
                f"release requires a passing freeze_candidate decision: {benchmark}"
            )

    if not resource_lock.resources:
        raise ValueError("resource lock must contain resolved resources")
    seen_uris: set[str] = set()
    allowed_prefixes = {
        "git": ("git+https://",),
        "rsebench-data": ("rsebench-data://",),
        "rsebench-methods": ("rsebench-methods://",),
        "external-image": ("oci://", "docker://"),
    }
    for resource in resource_lock.resources:
        if resource.uri in seen_uris:
            raise ValueError(f"resource lock contains duplicate URI: {resource.uri}")
        seen_uris.add(resource.uri)
        if not resource.uri.startswith(allowed_prefixes[resource.kind]):
            raise ValueError(
                f"resource URI does not match declared kind {resource.kind}: "
                f"{resource.uri}"
            )
        if not resource.materialization.strip():
            raise ValueError(f"resource materialization is unresolved: {resource.uri}")

def build_release_files(
    *,
    candidates: Mapping[str, StableSplitCandidate],
    confirmations: Mapping[str, ConfirmationSplit],
    decisions: Mapping[str, CandidateDecision],
    domain_statuses: Mapping[str, str],
    exposure_registry: ExposureRegistry,
    confirmation_seal: ConfirmationSeal,
    resource_lock: ResourceLock,
    baseline_fingerprints: Mapping[str, str],
) -> dict[str, bytes]:
    """Return canonical UTF-8 JSON bytes keyed by repository-relative path."""

    _validate_release_inputs(
        candidates=candidates,
        confirmations=confirmations,
        decisions=decisions,
        domain_statuses=domain_statuses,
        exposure_registry=exposure_registry,
        confirmation_seal=confirmation_seal,
        resource_lock=resource_lock,
        baseline_fingerprints=baseline_fingerprints,
    )
    manifest = SelectionReleaseManifest(
        selection_version="noise-screen-v1",
        selected_candidate_indices={
            benchmark: candidate.candidate_index
            for benchmark, candidate in sorted(candidates.items())
        },
        screening_split_hashes={
            benchmark: candidate.selection_hash
            for benchmark, candidate in sorted(candidates.items())
        },
        confirmation_split_hashes={
            benchmark: confirmation.selection_hash
            for benchmark, confirmation in sorted(confirmations.items())
        },
        exposure_registry_hash=exposure_registry.registry_hash,
        resource_lock_hash=canonical_hash(resource_lock.model_dump(mode="json")),
        baseline_fingerprints=dict(sorted(baseline_fingerprints.items())),
        domain_statuses=dict(sorted(domain_statuses.items())),
    )
    files: dict[str, bytes] = {
        "manifest.json": _canonical_json_bytes(manifest),
        "exposure_registry.json": _canonical_json_bytes(exposure_registry),
        "confirmation_seal.json": _canonical_json_bytes(confirmation_seal),
        "resource_lock.json": _canonical_json_bytes(resource_lock),
    }
    for benchmark in sorted(EXPECTED_DOMAINS):
        files[f"base_splits/{benchmark}.json"] = _canonical_json_bytes(
            candidates[benchmark]
        )
        files[f"confirmation_splits/{benchmark}.json"] = _canonical_json_bytes(
            confirmations[benchmark]
        )
        files[f"candidate_decisions/{benchmark}.json"] = _canonical_json_bytes(
            decisions[benchmark]
        )
    return dict(sorted(files.items()))


def _walk_values(value: Any, *, key: str | None = None) -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            normalized = str(child_key).casefold()
            if normalized in _CREDENTIAL_NAMES and child not in (None, "", False):
                raise ValueError(f"secret credential field detected: {child_key}")
            _walk_values(child, key=str(child_key))
        return
    if isinstance(value, list):
        for child in value:
            _walk_values(child, key=key)
        return
    if not isinstance(value, str):
        return
    folded = value.casefold()
    if ".worktrees" in folded:
        raise ValueError(f"worktree path detected in {key or 'value'}")
    if any(marker in folded for marker in _UNRESOLVED_MARKERS):
        raise ValueError(f"unresolved locator detected in {key or 'value'}")
    if (
        value.startswith("/")
        or _WINDOWS_ABSOLUTE.match(value)
        or _EMBEDDED_ABSOLUTE.search(value)
    ):
        raise ValueError(f"absolute path detected in {key or 'value'}")


def _validate_relative_file_name(name: str) -> None:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name:
        raise ValueError(f"release file name must be repository-relative: {name}")


def reject_secrets_and_absolute_paths(files: Mapping[str, bytes]) -> None:
    """Reject credentials, machine paths, worktrees, and unresolved locators."""

    for name, content in files.items():
        _validate_relative_file_name(name)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"release file is not UTF-8: {name}") from exc
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                raise ValueError(f"secret-like content detected in {name}")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"release file is not canonical JSON: {name}") from exc
        _walk_values(payload)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"existing release contains a symlink: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _file_hashes(files: Mapping[str, bytes]) -> dict[str, str]:
    return {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted(files.items())
    }


def atomic_content_addressed_write(
    destination: Path, files: Mapping[str, bytes]
) -> FrozenSelectionRelease:
    """Hash an ordered file map and atomically publish a sibling directory."""

    if not files:
        raise ValueError("selection release requires files")
    normalized = dict(sorted(files.items()))
    for name in normalized:
        _validate_relative_file_name(name)
    hashes = _file_hashes(normalized)
    release_id = canonical_hash([[name, digest] for name, digest in hashes.items()])
    target = Path(destination).resolve()
    if target.is_symlink():
        raise RuntimeError(f"existing release destination is a symlink: {target}")
    if target.exists():
        if not target.is_dir() or _tree_bytes(target) != normalized:
            raise RuntimeError(f"existing release content differs: {target}")
        return FrozenSelectionRelease(
            path=target,
            release_id=release_id,
            file_hashes=hashes,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.freeze-", dir=target.parent)
    )
    try:
        for name, content in normalized.items():
            output = temporary / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return FrozenSelectionRelease(
        path=target,
        release_id=release_id,
        file_hashes=hashes,
    )


def freeze_selection_release(
    *,
    destination: Path,
    candidates: Mapping[str, StableSplitCandidate],
    confirmations: Mapping[str, ConfirmationSplit],
    decisions: Mapping[str, CandidateDecision],
    domain_statuses: Mapping[str, str],
    exposure_registry: ExposureRegistry,
    confirmation_seal: ConfirmationSeal,
    resource_lock: ResourceLock,
    baseline_fingerprints: Mapping[str, str],
) -> FrozenSelectionRelease:
    """Freeze one release only after every portable selection barrier passes."""

    files = build_release_files(
        candidates=candidates,
        confirmations=confirmations,
        decisions=decisions,
        domain_statuses=domain_statuses,
        exposure_registry=exposure_registry,
        confirmation_seal=confirmation_seal,
        resource_lock=resource_lock,
        baseline_fingerprints=baseline_fingerprints,
    )
    reject_secrets_and_absolute_paths(files)
    return atomic_content_addressed_write(destination, files)


def freeze_selection_release_file(
    *, input_path: Path, destination: Path
) -> FrozenSelectionRelease:
    """Validate a strict input document and freeze it without provider calls."""

    payload = SelectionReleaseInput.model_validate_json(
        Path(input_path).read_text(encoding="utf-8")
    )
    return freeze_selection_release(
        destination=destination,
        candidates=payload.candidates,
        confirmations=payload.confirmations,
        decisions=payload.decisions,
        domain_statuses=payload.domain_statuses,
        exposure_registry=payload.exposure_registry,
        confirmation_seal=payload.confirmation_seal,
        resource_lock=payload.resource_lock,
        baseline_fingerprints=payload.baseline_fingerprints,
    )


__all__ = [
    "EXPECTED_BASELINES",
    "EXPECTED_DOMAINS",
    "FrozenSelectionRelease",
    "SelectionReleaseInput",
    "atomic_content_addressed_write",
    "build_release_files",
    "freeze_selection_release",
    "freeze_selection_release_file",
    "reject_secrets_and_absolute_paths",
    "validate_cross_release_disjointness",
]
