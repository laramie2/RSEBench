"""Replayable baseline patch series and deterministic source fingerprints."""

from __future__ import annotations

import hashlib
import os
import platform
import shlex
import subprocess
import tarfile
import tempfile
import warnings
from pathlib import Path
from typing import Any, Literal, Sequence

import yaml
from pydantic import Field

from rsebench.contracts import StrictModel
from rsebench.evidence import canonical_hash
from rsebench.hashing import sha256_file


class PatchEntry(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["provider", "evidence", "compatibility", "robustness"]


class PatchSeries(StrictModel):
    baseline: str = Field(min_length=1)
    upstream_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    patches: list[PatchEntry]


class BaselineFingerprint(StrictModel):
    baseline: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    upstream_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    patch_paths: list[str]
    patch_hashes: list[str]
    patchset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    python_version: str = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


_CHECKOUT_NAMES = {
    "skilllearn_self_feedback": "skilllearnbench",
    "skilllearn_teacher_feedback": "skilllearnbench",
}


def resolve_patch_series_path(path: Path | str) -> Path:
    """Resolve a canonical series path, with one-version old-layout fallback."""

    requested = Path(path).resolve()
    if requested.exists():
        return requested
    parts = requested.parts
    for index in range(len(parts) - 3):
        if parts[index : index + 2] != ("patches", "baselines"):
            continue
        project_root = Path(*parts[:index])
        method = parts[index + 2]
        tail = parts[index + 3 :]
        for lifecycle in ("validated", "candidates"):
            canonical = (
                project_root / "methods" / lifecycle / method / "patches" / Path(*tail)
            ).resolve()
            if canonical.exists():
                warnings.warn(
                    f"using canonical method patch for legacy locator {requested}",
                    DeprecationWarning,
                    stacklevel=2,
                )
                return canonical
    return requested


def _series_patch_paths(series_path: Path, series: PatchSeries) -> list[Path]:
    root = series_path.resolve().parent
    paths: list[Path] = []
    for entry in series.patches:
        relative = Path(entry.path)
        if relative.is_absolute():
            raise ValueError(f"patch path must be relative: {entry.path}")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"patch path escapes series directory: {entry.path}") from exc
        paths.append(candidate)
    return paths


def load_patch_series(path: Path | str) -> PatchSeries:
    """Load a series and prove that every registered patch still has its pin."""

    series_path = resolve_patch_series_path(path)
    payload = yaml.safe_load(series_path.read_text(encoding="utf-8"))
    series = PatchSeries.model_validate(payload)
    for entry, patch_path in zip(
        series.patches, _series_patch_paths(series_path, series), strict=True
    ):
        if not patch_path.is_file():
            raise FileNotFoundError(f"registered baseline patch is missing: {patch_path}")
        actual = sha256_file(patch_path)
        if actual != entry.sha256:
            raise ValueError(
                f"patch hash mismatch for {entry.path}: "
                f"expected {entry.sha256}, got {actual}"
            )
    return series


def patch_paths_for_series(
    series_path: Path | str, series: PatchSeries | None = None
) -> list[Path]:
    path = resolve_patch_series_path(series_path)
    loaded = series or load_patch_series(path)
    return _series_patch_paths(path, loaded)


def patch_hashes_for_series(series_path: Path | str) -> dict[str, str]:
    """Return basename-keyed hashes for compatibility with existing manifests."""

    path = resolve_patch_series_path(series_path)
    series = load_patch_series(path)
    return {
        Path(entry.path).name: entry.sha256
        for entry in series.patches
    }


def build_baseline_fingerprint(
    *,
    name: str,
    repository: str,
    revision: str,
    patch_paths: list[Path] | tuple[Path, ...],
    python_version: str | None = None,
) -> BaselineFingerprint:
    """Hash upstream identity and ordered patch bytes into one stable identity."""

    paths = [Path(path).resolve() for path in patch_paths]
    ordered_patches = [
        {"path": path.name, "sha256": sha256_file(path)} for path in paths
    ]
    patchset_hash = canonical_hash(ordered_patches)
    version = python_version or platform.python_version()
    payload = {
        "baseline": name,
        "repository": repository,
        "upstream_revision": revision,
        "patchset_hash": patchset_hash,
        "python_version": version,
    }
    return BaselineFingerprint(
        **payload,
        patch_paths=[item["path"] for item in ordered_patches],
        patch_hashes=[item["sha256"] for item in ordered_patches],
        fingerprint=canonical_hash(payload),
    )


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed in {root}: {detail}")
    return completed.stdout.strip()


def _changed_paths(root: Path) -> set[str]:
    tracked = _git(root, "diff", "--name-only", "-z", "HEAD").split("\0")
    untracked = _git(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    ).split("\0")
    return {path for path in tracked + untracked if path}


def _working_tree_snapshot(root: Path) -> dict[str, dict[str, str | int]]:
    snapshot: dict[str, dict[str, str | int]] = {}
    for relative in sorted(_changed_paths(root)):
        candidate = root / relative
        if not candidate.exists() and not candidate.is_symlink():
            snapshot[relative] = {"kind": "deleted"}
            continue
        stat = candidate.lstat()
        if candidate.is_symlink():
            payload = os.readlink(candidate).encode("utf-8")
            kind = "symlink"
        else:
            payload = candidate.read_bytes()
            kind = "file"
        snapshot[relative] = {
            "kind": kind,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "executable": int(bool(stat.st_mode & 0o111)),
        }
    return snapshot


def _patch_target_paths(patches: list[Path]) -> list[str]:
    targets: set[str] = set()
    for patch in patches:
        for line in patch.read_text(encoding="utf-8").splitlines():
            if line.startswith("diff --git "):
                fields = shlex.split(line)
                if len(fields) != 4 or not fields[3].startswith("b/"):
                    raise ValueError(
                        f"unsupported Git patch header in {patch}: {line}"
                    )
                targets.add(fields[3].removeprefix("b/"))
            elif line.startswith("+++ b/"):
                targets.add(line.removeprefix("+++ b/"))
    return sorted(targets)


def verify_baseline(
    method_root: Path | str,
    series: PatchSeries,
    *,
    series_path: Path | str,
    repository: str,
    revision: str,
    python_version: str | None = None,
) -> BaselineFingerprint:
    """Verify one patched checkout without changing its index or worktree."""

    root = Path(method_root).resolve()
    if not (root / ".git").exists():
        raise FileNotFoundError(f"baseline is not a Git checkout: {root}")
    if series.upstream_revision != revision:
        raise ValueError(
            f"series revision {series.upstream_revision} differs from registry {revision}"
        )
    actual_head = _git(root, "rev-parse", "HEAD")
    if actual_head != revision:
        raise RuntimeError(
            f"baseline revision mismatch: expected {revision}, got {actual_head}"
        )
    actual_origin = _git(root, "remote", "get-url", "origin")
    if actual_origin != repository:
        raise RuntimeError(
            f"baseline origin mismatch: expected {repository}, got {actual_origin}"
        )

    path = resolve_patch_series_path(series_path)
    loaded = load_patch_series(path)
    if loaded != series:
        raise ValueError("supplied patch series differs from the pinned series file")
    patches = patch_paths_for_series(path, loaded)

    with tempfile.TemporaryDirectory(
        prefix=".rsebench-baseline-", dir=root.parent
    ) as temporary:
        temporary_root = Path(temporary)
        expected_root = temporary_root / "expected"
        expected_root.mkdir()
        archive = temporary_root / "upstream.tar"
        upstream_paths = []
        for relative in _patch_target_paths(patches):
            exists = subprocess.run(
                ["git", "-C", str(root), "cat-file", "-e", f"{revision}:{relative}"],
                check=False,
                capture_output=True,
            )
            if exists.returncode == 0:
                upstream_paths.append(relative)
        if upstream_paths:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "archive",
                    "--format=tar",
                    f"--output={archive}",
                    revision,
                    "--",
                    *upstream_paths,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            with tarfile.open(archive) as upstream:
                upstream.extractall(expected_root, filter="fully_trusted")
        _git(expected_root, "init", "--quiet")
        _git(expected_root, "config", "user.email", "bootstrap@rsebench.local")
        _git(expected_root, "config", "user.name", "RSEBench Bootstrap")
        _git(expected_root, "add", "--all")
        _git(
            expected_root,
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "pinned upstream",
        )
        for patch in patches:
            _git(
                expected_root,
                "apply",
                "--ignore-space-change",
                "--ignore-whitespace",
                str(patch),
            )
        expected = _working_tree_snapshot(expected_root)

        # Reverse in dependency order on the disposable replay tree. This
        # validates each patch against the state produced by all earlier ones.
        for patch in reversed(patches):
            options = ("--ignore-space-change", "--ignore-whitespace")
            _git(
                expected_root,
                "apply",
                "--reverse",
                "--check",
                *options,
                str(patch),
            )
            _git(expected_root, "apply", "--reverse", *options, str(patch))
        reversed_diff = subprocess.run(
            ["git", "-C", str(expected_root), "diff", "--quiet", "-w", "HEAD"],
            check=False,
        )
        reversed_untracked = _git(
            expected_root, "ls-files", "--others", "--exclude-standard"
        ).splitlines()
        nonempty_untracked = [
            relative
            for relative in reversed_untracked
            if (expected_root / relative).read_bytes()
        ]
        if reversed_diff.returncode or nonempty_untracked:
            raise RuntimeError("patch series does not reverse to the pinned upstream tree")

    actual = _working_tree_snapshot(root)
    if actual != expected:
        expected_hash = canonical_hash(expected)
        actual_hash = canonical_hash(actual)
        raise RuntimeError(
            "unregistered baseline changes: "
            f"expected snapshot {expected_hash}, got {actual_hash}"
        )
    return build_baseline_fingerprint(
        name=series.baseline,
        repository=repository,
        revision=revision,
        patch_paths=patches,
        python_version=python_version,
    )


def _registered_methods(project_root: Path) -> dict[str, dict[str, Any]]:
    registry_path = project_root / "benchmark/registry/methods.yaml"
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    methods = payload.get("methods") if isinstance(payload, dict) else None
    if not isinstance(methods, dict):
        raise ValueError(f"invalid method registry: {registry_path}")
    return {
        str(name): dict(specification)
        for name, specification in methods.items()
        if specification.get("active") and specification.get("patch_series")
    }


def _selected_registered_methods(
    project_root: Path,
    names: Sequence[str] | None,
) -> dict[str, dict[str, Any]]:
    methods = _registered_methods(project_root)
    if names is None:
        return methods
    selected: dict[str, dict[str, Any]] = {}
    for name in names:
        if name not in methods:
            raise ValueError(f"unknown active patched baseline: {name}")
        selected[name] = methods[name]
    return selected


def verify_registered_baselines(
    *,
    project_root: Path | str,
    methods_root: Path | str | None = None,
    names: Sequence[str] | None = None,
) -> dict[str, BaselineFingerprint]:
    """Verify all selected pinned baseline checkouts without changing them."""

    root = Path(project_root).resolve()
    external = Path(methods_root or root / "methods/external").resolve()
    fingerprints: dict[str, BaselineFingerprint] = {}
    for name, specification in _selected_registered_methods(root, names).items():
        series_path = (root / str(specification["patch_series"])).resolve()
        series = load_patch_series(series_path)
        checkout = external / _CHECKOUT_NAMES.get(name, name)
        fingerprints[name] = verify_baseline(
            checkout,
            series,
            series_path=series_path,
            repository=str(specification["repository"]),
            revision=str(specification["commit"]),
        )
    return fingerprints


def _run_git(*arguments: str, cwd: Path | None = None) -> None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")


def bootstrap_registered_baselines(
    *,
    project_root: Path | str,
    methods_root: Path | str | None = None,
    names: Sequence[str] | None = None,
) -> dict[str, BaselineFingerprint]:
    """Clone or patch selected baselines, refusing to overwrite unknown changes."""

    root = Path(project_root).resolve()
    external = Path(methods_root or root / "methods/external").resolve()
    external.mkdir(parents=True, exist_ok=True)
    methods = _selected_registered_methods(root, names)
    completed_checkouts: set[Path] = set()
    for name, specification in methods.items():
        checkout = external / _CHECKOUT_NAMES.get(name, name)
        if checkout in completed_checkouts:
            continue
        repository = str(specification["repository"])
        revision = str(specification["commit"])
        series_path = (root / str(specification["patch_series"])).resolve()
        series = load_patch_series(series_path)
        if checkout.exists() and not (checkout / ".git").is_dir():
            raise RuntimeError(
                f"refusing to overwrite a non-Git baseline target: {checkout}"
            )
        if not checkout.exists():
            _run_git("clone", "--filter=blob:none", repository, str(checkout))
        origin = _git(checkout, "remote", "get-url", "origin")
        if origin != repository:
            raise RuntimeError(
                f"baseline origin mismatch: expected {repository}, got {origin}"
            )
        head = _git(checkout, "rev-parse", "HEAD")
        if head != revision:
            if _git(checkout, "status", "--porcelain"):
                raise RuntimeError(
                    f"refusing to change dirty baseline checkout: {checkout}"
                )
            _run_git("-C", str(checkout), "fetch", "--depth", "1", "origin", revision)
            _run_git("-C", str(checkout), "checkout", "--detach", revision)
        try:
            verify_baseline(
                checkout,
                series,
                series_path=series_path,
                repository=repository,
                revision=revision,
            )
        except RuntimeError as exc:
            if _git(checkout, "status", "--porcelain"):
                raise RuntimeError(
                    f"refusing to replace unregistered baseline changes: {checkout}"
                ) from exc
            for patch in patch_paths_for_series(series_path, series):
                _run_git(
                    "-C",
                    str(checkout),
                    "apply",
                    "--ignore-space-change",
                    "--ignore-whitespace",
                    str(patch),
                )
        completed_checkouts.add(checkout)
    return verify_registered_baselines(
        project_root=root,
        methods_root=external,
        names=list(methods),
    )


__all__ = [
    "BaselineFingerprint",
    "PatchEntry",
    "PatchSeries",
    "bootstrap_registered_baselines",
    "build_baseline_fingerprint",
    "load_patch_series",
    "patch_hashes_for_series",
    "patch_paths_for_series",
    "verify_baseline",
    "verify_registered_baselines",
]
