"""Canonical JSON serialization for evidence records and replay packs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from rsebench.evidence.contracts import EvidenceRecord


_RECORD_ADAPTER = TypeAdapter(EvidenceRecord)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def write_record(path: str | Path, record: BaseModel | dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(record) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=destination.parent,
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, destination)


def read_record(path: str | Path) -> EvidenceRecord:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return _RECORD_ADAPTER.validate_python(payload)

