from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsebench.domains.officeqa_materialization import (
    build_parsed_page_index,
    materialize_referenced_parsed_pages,
    validate_officeqa_parsed_pages,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_validate_parsed_pages_requires_every_referenced_source(tmp_path: Path) -> None:
    rows = [{"source_files": "a.txt\r\nb.txt"}]
    _write_json(tmp_path / "jsons/a.json", [])

    with pytest.raises(FileNotFoundError, match="b.json"):
        validate_officeqa_parsed_pages(rows, tmp_path)


def test_index_contains_only_relative_paths_sizes_and_hashes(tmp_path: Path) -> None:
    source = tmp_path / "jsons/a.json"
    _write_json(source, {"document": {"elements": []}})

    index = build_parsed_page_index([source], tmp_path)

    assert index[0]["path"] == "jsons/a.json"
    assert index[0]["size"] == source.stat().st_size
    assert len(index[0]["sha256"]) == 64
    assert str(tmp_path) not in json.dumps(index)


def test_materialization_hardlinks_only_referenced_sources(tmp_path: Path) -> None:
    raw = tmp_path / "raw/treasury_bulletins_parsed/jsons"
    _write_json(raw / "a.json", {"id": "a"})
    _write_json(raw / "unused.json", {"id": "unused"})
    destination = tmp_path / "materialized/parsed"

    paths = materialize_referenced_parsed_pages(
        [{"source_files": "a.txt"}],
        raw_root=tmp_path / "raw",
        destination_root=destination,
    )

    assert paths == [destination / "jsons/a.json"]
    assert not (destination / "jsons/unused.json").exists()
    assert (destination / "jsons/a.json").stat().st_ino == (raw / "a.json").stat().st_ino
