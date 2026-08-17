"""Validated/candidate method catalog and local source compatibility lookup."""

from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator

from rsebench.datasets.contracts import FrozenStrictModel
from rsebench.methods.contracts import MethodRelease


class MethodMetadata(FrozenStrictModel):
    schema_version: Literal["rsebench.method.v1"] = "rsebench.method.v1"
    method: str = Field(min_length=1)
    status: Literal["active", "validated_inactive", "candidate"]
    upstream_repository: str = Field(min_length=1)
    upstream_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_status: str = Field(min_length=1)
    local_checkout: str = Field(min_length=1)
    releases: tuple[str, ...] = ()

    @field_validator("upstream_repository")
    @classmethod
    def require_https_upstream(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("upstream repository must use HTTPS")
        return value


class MethodCatalog:
    """Read and verify all method metadata below one canonical methods root."""

    def __init__(
        self,
        root: Path,
        metadata: dict[str, MethodMetadata],
        releases: dict[str, MethodRelease],
    ) -> None:
        self.root = root
        self._metadata = metadata
        self._releases = releases

    @classmethod
    def load(cls, root: Path | str) -> "MethodCatalog":
        methods_root = Path(root).resolve()
        metadata: dict[str, MethodMetadata] = {}
        releases: dict[str, MethodRelease] = {}
        for lifecycle in ("validated", "candidates"):
            for metadata_path in sorted((methods_root / lifecycle).glob("*/method.yaml")):
                item = MethodMetadata.model_validate(
                    yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
                )
                if item.method in metadata:
                    raise ValueError(f"duplicate method metadata: {item.method}")
                expected_status = "candidate" if lifecycle == "candidates" else None
                if expected_status and item.status != expected_status:
                    raise ValueError(
                        f"candidate directory has non-candidate status: {item.method}"
                    )
                if lifecycle == "validated" and item.status == "candidate":
                    raise ValueError(
                        f"validated directory has candidate status: {item.method}"
                    )
                metadata[item.method] = item

                release_root = metadata_path.parent / "releases"
                found_release_ids: list[str] = []
                for release_path in sorted(release_root.glob("*.json")):
                    release = MethodRelease.model_validate(
                        json.loads(release_path.read_text(encoding="utf-8"))
                    )
                    if release.method != item.method:
                        raise ValueError(
                            f"release method differs from directory: {release.release_id}"
                        )
                    if release.status != item.status:
                        raise ValueError(
                            f"release lifecycle differs from method: {release.release_id}"
                        )
                    if release.release_id in releases:
                        raise ValueError(f"duplicate method release: {release.release_id}")
                    cls._verify_release_files(methods_root, release)
                    releases[release.release_id] = release
                    found_release_ids.append(release.release_id)
                if tuple(found_release_ids) != item.releases:
                    raise ValueError(f"declared releases differ for {item.method}")
        return cls(methods_root, metadata, releases)

    @staticmethod
    def _project_path(methods_root: Path, uri: str) -> Path:
        prefix = "rsebench-project://"
        if not uri.startswith(prefix):
            raise ValueError(f"method catalog requires a project URI: {uri}")
        project_root = methods_root.parent
        candidate = (project_root / uri.removeprefix(prefix)).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(f"method URI escapes project root: {uri}") from exc
        return candidate

    @classmethod
    def _verify_release_files(
        cls, methods_root: Path, release: MethodRelease
    ) -> None:
        for patch in release.patch_series:
            path = cls._project_path(methods_root, patch.uri)
            if not path.is_file():
                raise FileNotFoundError(f"registered method patch is missing: {path}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != patch.sha256:
                raise ValueError(
                    f"method patch hash mismatch for {patch.uri}: {actual}"
                )
        lock = cls._project_path(methods_root, release.environment_lock)
        if not lock.is_file():
            raise FileNotFoundError(f"method environment lock is missing: {lock}")

    def active_releases(self) -> tuple[MethodRelease, ...]:
        return tuple(
            release
            for _, release in sorted(self._releases.items())
            if release.status == "active"
        )

    def releases(self) -> tuple[MethodRelease, ...]:
        return tuple(release for _, release in sorted(self._releases.items()))

    def method_status(
        self, method: str
    ) -> Literal["active", "validated_inactive", "candidate"]:
        try:
            return self._metadata[method].status
        except KeyError as exc:
            raise KeyError(f"unknown method: {method}") from exc

    def require_active(self, identity: str) -> MethodRelease:
        release = self._releases.get(identity)
        if release is not None:
            if release.status != "active":
                raise ValueError(f"method release is not active: {identity}")
            return release
        metadata = self._metadata.get(identity)
        if metadata is None:
            raise KeyError(f"unknown method or release: {identity}")
        matches = tuple(
            release
            for release in self.active_releases()
            if release.method == identity
        )
        if metadata.status != "active" or not matches:
            raise ValueError(f"method is not active: {identity}")
        if len(matches) != 1:
            raise ValueError(f"active method requires an exact release ID: {identity}")
        return matches[0]

    def resolve_method_source(self, method: str) -> Path:
        try:
            metadata = self._metadata[method]
        except KeyError as exc:
            raise KeyError(f"unknown method: {method}") from exc
        lifecycle = "candidates" if metadata.status == "candidate" else "validated"
        canonical = (self.root / lifecycle / method / "source").resolve()
        if canonical.exists():
            return canonical
        legacy = (self.root / "external" / metadata.local_checkout).resolve()
        if legacy.exists():
            warnings.warn(
                f"using legacy method source for {method}: {legacy}",
                DeprecationWarning,
                stacklevel=2,
            )
            return legacy
        return canonical


__all__ = ["MethodCatalog", "MethodMetadata"]
