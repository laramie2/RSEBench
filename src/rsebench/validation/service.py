"""Provider-free validation preflight and unified matrix control-plane services."""

from __future__ import annotations

import importlib
import json
import subprocess
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from rsebench.datasets import resolve_portable_uri
from rsebench.experiments.scheduler import ExperimentScheduler
from rsebench.methods import MethodRelease
from rsebench.validation.matrix import (
    ValidationCatalogs,
    expand_validation_cells,
    load_validation_matrix,
)
from rsebench.validation.scheduler import build_validation_units


def _project_root(matrix_path: Path) -> Path:
    for candidate in (matrix_path.parent, *matrix_path.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ValueError(f"cannot locate project root above matrix: {matrix_path}")


def _project_path(root: Path, uri: str) -> Path:
    prefix = "rsebench-project://"
    if not uri.startswith(prefix):
        raise ValueError(f"release resource must use a project URI: {uri}")
    path = (root / uri.removeprefix(prefix)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"release resource escapes project root: {uri}") from exc
    return path


def _artifact_uris(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            found.update(_artifact_uris(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_artifact_uris(child))
    elif isinstance(value, str) and value.startswith("rsebench-data://"):
        found.add(value)
    return found


def _verify_dataset_artifacts(root: Path, catalogs: ValidationCatalogs) -> int:
    uris: set[str] = set()
    for release in catalogs.datasets.values():
        for task in release.tasks.values():
            if task.artifact_path and task.artifact_path.startswith("rsebench-data://"):
                uris.add(task.artifact_path)
            uris.update(_artifact_uris(task.metadata))
    missing: list[str] = []
    for uri in sorted(uris):
        path = resolve_portable_uri(uri, roots={"rsebench-data": root / "data"})
        if not path.exists():
            missing.append(uri)
    if missing:
        preview = ", ".join(missing[:3])
        raise FileNotFoundError(
            f"validation dataset artifacts are missing ({len(missing)}): {preview}"
        )
    return len(uris)


def _git(source: Path, *arguments: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed in {source}: {detail}")
    return completed.stdout.strip()


def _verify_release_patch_replay(
    root: Path,
    catalogs: ValidationCatalogs,
    release: MethodRelease,
) -> None:
    source = catalogs.methods.resolve_method_source(release.method)
    if not (source / ".git").is_dir():
        raise FileNotFoundError(f"method source is not a Git checkout: {source}")
    origin = _git(source, "remote", "get-url", "origin")
    if origin != release.upstream_repository:
        raise RuntimeError(
            f"method source origin differs for {release.release_id}: {origin}"
        )
    _git(source, "cat-file", "-e", f"{release.upstream_revision}^{{commit}}")
    with tempfile.TemporaryDirectory(prefix="rsebench-release-replay-") as temporary:
        temporary_root = Path(temporary)
        archive = temporary_root / "upstream.tar"
        checkout = temporary_root / "checkout"
        _git(
            source,
            "archive",
            "--format=tar",
            f"--output={archive}",
            release.upstream_revision,
        )
        checkout.mkdir()
        with tarfile.open(archive) as handle:
            handle.extractall(checkout, filter="fully_trusted")
        _git(checkout, "init", "--quiet")
        for patch in release.patch_series:
            patch_path = _project_path(root, patch.uri)
            _git(
                checkout,
                "apply",
                "--ignore-space-change",
                "--ignore-whitespace",
                str(patch_path),
            )


def _load_plugin_object(entrypoint: str) -> Any:
    module_name, attribute = entrypoint.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute)


def _operator_implementation_status(cells, catalogs: ValidationCatalogs):
    status: dict[str, str] = {}
    for cell in cells:
        plugin = catalogs.plugins[cell.stage]
        _load_plugin_object(plugin.entrypoint)
        module = importlib.import_module(plugin.operators_root)
        runners = getattr(module, "CELL_RUNNERS", {})
        implemented = isinstance(runners, dict) and callable(
            runners.get(cell.operator)
        )
        status[cell.cell_id] = "implemented" if implemented else "interface_only"
    return status


def preflight_validation(matrix_path: Path | str) -> dict[str, Any]:
    """Validate all immutable inputs without creating a provider client."""

    path = Path(matrix_path).resolve()
    root = _project_root(path)
    matrix = load_validation_matrix(path)
    catalogs = ValidationCatalogs.load(root)
    cells = expand_validation_cells(matrix, catalogs)
    artifact_count = _verify_dataset_artifacts(root, catalogs)
    replay: dict[str, str] = {}
    for release in catalogs.methods.active_releases():
        _verify_release_patch_replay(root, catalogs, release)
        replay[release.release_id] = "passed"
    implementation = _operator_implementation_status(cells, catalogs)
    execution_ready = all(value == "implemented" for value in implementation.values())
    return {
        "schema_version": "rsebench.validation-preflight.v1",
        "matrix": str(path.relative_to(root)),
        "matrix_hash": matrix.content_hash,
        "cell_count": len(cells),
        "ready_cell_count": len(cells),
        "domains": list(matrix.datasets),
        "stages": list(matrix.stages),
        "dataset_release_count": len(matrix.datasets),
        "active_method_release_count": len(
            {cell.method_release_id for cell in cells}
        ),
        "plugin_count": len(catalogs.plugins),
        "artifact_locator_count": artifact_count,
        "release_patch_replay": dict(sorted(replay.items())),
        "operator_implementations": implementation,
        "execution_ready": execution_ready,
        "provider_calls": 0,
    }


def validation_status(
    matrix_path: Path | str,
    run_root: Path | str,
) -> dict[str, Any]:
    path = Path(matrix_path).resolve()
    root = _project_root(path)
    matrix = load_validation_matrix(path)
    cells = expand_validation_cells(matrix, ValidationCatalogs.load(root))
    status_path = Path(run_root).resolve() / "matrix_status.json"
    stored: dict[str, Any] = {}
    if status_path.is_file():
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        stored = payload.get("units", {})
    rows = [
        {
            "cell_id": cell.cell_id,
            "identity_hash": cell.identity_hash,
            "state": str(stored.get(cell.cell_id, {}).get("state", "pending")),
        }
        for cell in cells
    ]
    states = dict(sorted(Counter(row["state"] for row in rows).items()))
    return {
        "schema_version": "rsebench.validation-status.v1",
        "matrix_hash": matrix.content_hash,
        "cell_count": len(rows),
        "states": states,
        "cells": rows,
    }


def aggregate_validation(
    matrix_path: Path | str,
    run_root: Path | str,
) -> dict[str, Any]:
    """Aggregate the fixed 16-cell denominator without dropping terminal states."""

    status = validation_status(matrix_path, run_root)
    return {
        "schema_version": "rsebench.validation-aggregate.v1",
        "matrix_hash": status["matrix_hash"],
        "fixed_denominator": status["cell_count"],
        "states": status["states"],
        "cells": status["cells"],
    }


def run_validation(
    matrix_path: Path | str,
    run_root: Path | str,
    *,
    max_parallel: int,
    confirm_provider_cost: bool,
) -> list[dict[str, Any]]:
    if not confirm_provider_cost:
        raise ValueError("--confirm-provider-cost is required")
    report = preflight_validation(matrix_path)
    if not report["execution_ready"]:
        raise RuntimeError(
            "validation operators are interface-only; concrete CELL_RUNNERS must be "
            "registered before provider-backed execution"
        )
    path = Path(matrix_path).resolve()
    root = _project_root(path)
    matrix = load_validation_matrix(path)
    cells = expand_validation_cells(matrix, ValidationCatalogs.load(root))
    units = build_validation_units(cells, run_root, project_root=root)
    git_head = _git(root, "rev-parse", "HEAD")
    scheduler = ExperimentScheduler(
        run_root=run_root,
        project_root=root,
        max_parallel=max_parallel,
        status_metadata={
            "config_hash": matrix.content_hash,
            "git_head": git_head,
            "expected_units": 16,
        },
    )
    return scheduler.run(units)


__all__ = [
    "aggregate_validation",
    "preflight_validation",
    "run_validation",
    "validation_status",
]
