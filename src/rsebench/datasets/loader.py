"""Load frozen benchmark releases and resolve their portable resources."""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path

from rsebench.contracts import TaskManifest
from rsebench.datasets.contracts import DatasetRelease


class BenchmarkDataset:
    """Read-only task access over one DatasetRelease."""

    def __init__(self, release: DatasetRelease) -> None:
        self.release = release

    def task(self, task_id: str) -> TaskManifest:
        try:
            return self.release.tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown dataset task: {task_id}") from exc

    def partition(self, name: str) -> tuple[TaskManifest, ...]:
        try:
            members = self.release.partitions[name]
        except KeyError as exc:
            raise KeyError(f"unknown dataset partition: {name}") from exc
        return tuple(self.task(task_id) for task_id in members)

    def group(self, name: str) -> tuple[TaskManifest, ...]:
        try:
            members = self.release.groups[name]
        except KeyError as exc:
            raise KeyError(f"unknown dataset group: {name}") from exc
        return tuple(self.task(task_id) for task_id in members)

    def group_names(self) -> tuple[str, ...]:
        return tuple(self.release.groups)


def load_dataset_release(path: Path | str) -> DatasetRelease:
    """Load and validate a frozen dataset release JSON document."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return DatasetRelease.model_validate(payload)


def resolve_portable_uri(
    uri: str,
    *,
    roots: Mapping[str, Path | str],
    legacy_roots: Mapping[str, Sequence[Path | str]] | None = None,
) -> Path:
    """Resolve a portable URI, preferring canonical roots over legacy roots."""

    for scheme, configured_root in roots.items():
        prefix = f"{scheme}://"
        if not uri.startswith(prefix):
            continue
        relative = uri.removeprefix(prefix)
        root = Path(configured_root).resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"portable URI escapes {scheme}: {uri}") from exc
        if candidate.exists():
            return candidate
        for legacy_value in (legacy_roots or {}).get(scheme, ()):
            legacy_root = Path(legacy_value).resolve()
            legacy_candidate = (legacy_root / relative).resolve()
            try:
                legacy_candidate.relative_to(legacy_root)
            except ValueError as exc:
                raise ValueError(f"portable URI escapes legacy {scheme}: {uri}") from exc
            if legacy_candidate.exists():
                warnings.warn(
                    f"using legacy {scheme} root for {uri}",
                    DeprecationWarning,
                    stacklevel=2,
                )
                return legacy_candidate
        return candidate
    raise ValueError(f"unsupported portable URI: {uri}")


__all__ = ["BenchmarkDataset", "load_dataset_release", "resolve_portable_uri"]
