"""Materialize the parsed OfficeQA pages referenced by released benchmark rows."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from rsebench.hashing import sha256_file


def _source_names(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        raw = row.get("source_files")
        if isinstance(raw, (list, tuple)):
            values = [str(value) for value in raw]
        else:
            text = str(raw or "").strip()
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                decoded = None
            values = (
                [str(value) for value in decoded]
                if isinstance(decoded, list)
                else text.replace("\\r\\n", "\n").splitlines()
            )
        for value in values:
            name = Path(value.strip()).name
            if name:
                names.add(name)
    return sorted(names)


def _json_name(source_name: str) -> str:
    source = Path(source_name)
    return f"{source.stem if source.suffix else source.name}.json"


def validate_officeqa_parsed_pages(
    rows: Iterable[Mapping[str, Any]], parsed_root: Path | str
) -> list[Path]:
    """Return ordered parsed files or fail if any released source is absent."""

    root = Path(parsed_root)
    paths = [root / "jsons" / _json_name(name) for name in _source_names(rows)]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        preview = ", ".join(missing[:10])
        raise FileNotFoundError(
            f"OfficeQA parsed pages are missing {len(missing)} file(s): {preview}"
        )
    return paths


def build_parsed_page_index(
    paths: Iterable[Path | str], parsed_root: Path | str
) -> list[dict[str, str | int]]:
    """Build a location-independent integrity index for materialized JSON files."""

    root = Path(parsed_root).resolve()
    records: list[dict[str, str | int]] = []
    for raw_path in sorted((Path(path).resolve() for path in paths), key=str):
        try:
            relative = raw_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"parsed page is outside materialized root: {raw_path}") from exc
        records.append(
            {
                "path": relative.as_posix(),
                "size": raw_path.stat().st_size,
                "sha256": sha256_file(raw_path),
            }
        )
    return records


def _raw_json_root(raw_root: Path) -> Path:
    candidates = (
        raw_root / "treasury_bulletins_parsed/jsons",
        raw_root / "jsons",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "OfficeQA raw parsed JSON directory not found under " f"{raw_root}"
    )


def materialize_referenced_parsed_pages(
    rows: Iterable[Mapping[str, Any]],
    *,
    raw_root: Path | str,
    destination_root: Path | str,
) -> list[Path]:
    """Hard-link only released source references, copying across filesystems."""

    row_list = list(rows)
    source_root = _raw_json_root(Path(raw_root))
    destination = Path(destination_root)
    json_destination = destination / "jsons"
    json_destination.mkdir(parents=True, exist_ok=True)
    materialized: list[Path] = []
    for source_name in _source_names(row_list):
        json_name = _json_name(source_name)
        source = source_root / json_name
        target = json_destination / json_name
        if not source.is_file():
            raise FileNotFoundError(f"raw OfficeQA parsed page missing: {json_name}")
        if target.exists():
            if not target.is_file() or sha256_file(target) != sha256_file(source):
                raise FileExistsError(
                    f"materialized OfficeQA parsed page differs: {target}"
                )
        else:
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        materialized.append(target)
    return validate_officeqa_parsed_pages(row_list, destination)
