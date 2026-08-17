"""Catalog loading and exact expansion of the frozen four-by-four matrix."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rsebench.datasets import DatasetRelease, load_dataset_release
from rsebench.evidence import canonical_hash
from rsebench.methods import MethodCatalog
from rsebench.noise import NoisePlugin, discover_noise_plugins
from rsebench.validation.contracts import (
    ValidationCell,
    ValidationMatrix,
)


_DOMAINS = ("spreadsheet", "document", "interactive", "skill")


def _project_root(path: Path) -> Path:
    for candidate in (path.parent, *path.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ValueError(f"cannot locate project root above matrix: {path}")


def _project_uri(root: Path, uri: str) -> Path:
    prefix = "rsebench-project://"
    if not uri.startswith(prefix):
        raise ValueError(f"clean evidence must use a project URI: {uri}")
    path = (root / uri.removeprefix(prefix)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"clean evidence URI escapes project root: {uri}") from exc
    return path


def _identity_values(value: Any, key: str) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for name, child in value.items():
            if name == key and isinstance(child, str):
                found.add(child)
            found.update(_identity_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.update(_identity_values(child, key))
    return found


@dataclass(frozen=True)
class ValidationCatalogs:
    project_root: Path
    datasets: dict[str, DatasetRelease]
    methods: MethodCatalog
    plugins: dict[str, NoisePlugin]

    @classmethod
    def load(cls, project_root: Path | str) -> "ValidationCatalogs":
        root = Path(project_root).resolve()
        datasets: dict[str, DatasetRelease] = {}
        manifests = sorted(
            (root / "benchmark/datasets").glob("*/*/releases/*/manifest.json")
        )
        for path in manifests:
            release = load_dataset_release(path)
            if release.release_id in datasets:
                raise ValueError(f"duplicate dataset release: {release.release_id}")
            datasets[release.release_id] = release
        plugins = {
            plugin.stage: plugin for plugin in discover_noise_plugins(root)
        }
        return cls(
            project_root=root,
            datasets=datasets,
            methods=MethodCatalog.load(root / "methods"),
            plugins=plugins,
        )


def load_validation_matrix(path: Path | str) -> ValidationMatrix:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ValidationMatrix.model_validate(payload)


def _verify_clean_evidence(catalogs: ValidationCatalogs, release) -> str:
    fingerprint_values: set[str] = set()
    for reference in release.clean_evidence:
        path = _project_uri(catalogs.project_root, reference.uri)
        if not path.is_file():
            raise FileNotFoundError(f"clean evidence is missing: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != reference.sha256:
            raise ValueError(f"clean evidence hash differs for {reference.uri}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        fingerprint_values.update(_identity_values(payload, "baseline_fingerprint"))
        fingerprint_values.update(
            _identity_values(payload, "baseline_patch_fingerprint")
        )
    if release.baseline_fingerprint not in fingerprint_values:
        raise ValueError(
            "clean evidence fingerprint differs for method release "
            f"{release.release_id}"
        )
    return canonical_hash(
        [reference.model_dump(mode="json") for reference in release.clean_evidence]
    )


def expand_validation_cells(
    matrix: ValidationMatrix,
    catalogs: ValidationCatalogs,
) -> tuple[ValidationCell, ...]:
    """Bind releases/plugins and expand exactly 16 independently runnable cells."""

    effective_matrix_hash = canonical_hash(
        matrix.model_dump(mode="json", exclude={"content_hash"})
    )
    cells: list[ValidationCell] = []
    for domain in _DOMAINS:
        dataset_id = matrix.datasets[domain]
        try:
            dataset = catalogs.datasets[dataset_id]
        except KeyError as exc:
            raise KeyError(f"unknown dataset release: {dataset_id}") from exc
        if dataset.domain != domain:
            raise ValueError(f"dataset domain differs for {dataset_id}")
        method = catalogs.methods.require_active(matrix.methods[domain])
        if dataset_id not in method.supported_datasets:
            raise ValueError(
                f"method release {method.release_id} does not support dataset {dataset_id}"
            )
        if method.provider.family != matrix.provider.family:
            raise ValueError(f"provider family differs for {method.release_id}")
        if method.provider.model != matrix.provider.model:
            raise ValueError(f"provider model differs for {method.release_id}")
        clean_evidence_hash = _verify_clean_evidence(catalogs, method)

        for stage in matrix.stages:
            plugin = catalogs.plugins[stage]
            expected_form = "static" if stage in {"N1", "N2"} else "runtime"
            if plugin.form != expected_form:
                raise ValueError(f"plugin form differs for {stage}")
            identity = {
                "matrix_hash": effective_matrix_hash,
                "domain": domain,
                "stage": stage,
                "form": plugin.form,
                "operator": matrix.operators[domain][stage],
                "plugin": plugin.model_dump(mode="json"),
                "dataset_release_id": dataset.release_id,
                "dataset_release_hash": dataset.content_hash,
                "method_release_id": method.release_id,
                "method_release_hash": method.content_hash,
                "baseline_fingerprint": method.baseline_fingerprint,
                "clean_evidence_hash": clean_evidence_hash,
                "provider": matrix.provider.model_dump(mode="json"),
                "runtime": matrix.runtime[domain],
                "noise_seed": matrix.noise_seed,
                "source_mode": matrix.source_modes[domain],
                "arm": "noisy",
            }
            identity_hash = canonical_hash(identity)
            cells.append(
                ValidationCell(
                    matrix_release_id=matrix.release_id,
                    matrix_hash=effective_matrix_hash,
                    cell_id=(
                        f"{matrix.release_id}--{domain}--{stage.lower()}"
                        f"--{identity_hash[:12]}"
                    ),
                    identity_hash=identity_hash,
                    domain=domain,
                    stage=stage,
                    form=plugin.form,
                    operator=matrix.operators[domain][stage],
                    plugin_entrypoint=plugin.entrypoint,
                    plugin_version=plugin.version,
                    dataset_release_id=dataset.release_id,
                    dataset_release_hash=dataset.content_hash,
                    method_release_id=method.release_id,
                    method_release_hash=method.content_hash,
                    baseline_fingerprint=method.baseline_fingerprint,
                    clean_evidence=method.clean_evidence,
                    clean_evidence_hash=clean_evidence_hash,
                    provider=matrix.provider,
                    runtime=matrix.runtime[domain],
                    noise_seed=matrix.noise_seed,
                    source_mode=matrix.source_modes[domain],
                )
            )
    if len(cells) != 16 or len({cell.cell_id for cell in cells}) != 16:
        raise ValueError("validation matrix must expand to 16 unique cells")
    return tuple(cells)


def load_and_expand(path: Path | str) -> tuple[ValidationCell, ...]:
    matrix_path = Path(path).resolve()
    matrix = load_validation_matrix(matrix_path)
    return expand_validation_cells(
        matrix,
        ValidationCatalogs.load(_project_root(matrix_path)),
    )


__all__ = [
    "ValidationCatalogs",
    "expand_validation_cells",
    "load_and_expand",
    "load_validation_matrix",
]
