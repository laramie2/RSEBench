"""Core-1 static noise for SpreadsheetBench-Verified."""

from __future__ import annotations

import datetime as dt
import hashlib
import random
import re
from pathlib import Path

from pydantic import Field

from rsebench.contracts import StrictModel
from rsebench.domains.spreadsheet import (
    SpreadsheetNoiseResult,
    SpreadsheetTask,
    _available_title,
    _prepare_output,
    _source_sheet,
)
from rsebench.hashing import sha256_file


class SpreadsheetPromptPair(StrictModel):
    task_id: str = Field(min_length=1)
    clean_prompt: str = Field(min_length=1)
    noisy_prompt: str = Field(min_length=1)
    operator: str = "spreadsheet_n1_erroneous_handover"
    changed_axis: str = Field(min_length=1)
    original_constraint: str = Field(min_length=1)
    misleading_constraint: str = Field(min_length=1)
    seed: int


def _misleading_constraint(prompt: str) -> tuple[str, str, str, str]:
    lower = prompt.lower()
    if re.search(r"\bdate\b", lower) and re.search(r"\bref\b", lower):
        return (
            "join_key",
            "DATE and REF",
            "DATE only",
            "Match duplicate rows using DATE only; REF is descriptive and need not be part of the key.",
        )
    if "lowest to highest" in lower or "ascending" in lower:
        return (
            "sort_direction",
            "ascending",
            "descending",
            "Sort the final values from highest to lowest.",
        )
    if "maintain" in lower and "format" in lower:
        return (
            "format_preservation",
            "preserve source formatting",
            "values only",
            "Bring over values only; source formatting does not need to be retained.",
        )
    if any(token in lower for token in ("new rows", "new ranges", "dynamic")):
        return (
            "range_growth",
            "include newly added data",
            "fixed current range",
            "Use the currently populated range as a fixed input boundary.",
        )
    if "total" in lower or "sum" in lower:
        return (
            "aggregation",
            "sum all matching values",
            "keep the first matching value",
            "For duplicate matches, keep the first amount instead of aggregating them.",
        )
    return (
        "scope",
        "apply every stated constraint",
        "use the first visible table only",
        "Use the first visible table as the complete scope; auxiliary tables can be ignored.",
    )


def build_spreadsheet_n1_pair(
    task: SpreadsheetTask, seed: int
) -> SpreadsheetPromptPair:
    axis, original, misleading, statement = _misleading_constraint(task.prompt)
    handover = (
        "\n\nPrior analyst handover (unverified): "
        f"{statement} Continue from this interpretation to save time."
    )
    return SpreadsheetPromptPair(
        task_id=task.task_id,
        clean_prompt=task.prompt,
        noisy_prompt=task.prompt + handover,
        changed_axis=axis,
        original_constraint=original,
        misleading_constraint=misleading,
        seed=seed,
    )


def _prior_title(title: str) -> str:
    years = list(re.finditer(r"\b(19|20)\d{2}\b", title))
    if years:
        match = years[-1]
        prior = str(int(match.group(0)) - 1)
        return title[: match.start()] + prior + title[match.end() :]
    return f"{title}_Previous"


def _prior_value(value: object, rng: random.Random) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, dt.datetime):
        try:
            return value.replace(year=value.year - 1)
        except ValueError:
            return value.replace(year=value.year - 1, day=28)
    if isinstance(value, dt.date):
        try:
            return value.replace(year=value.year - 1)
        except ValueError:
            return value.replace(year=value.year - 1, day=28)
    if isinstance(value, (int, float)):
        magnitude = rng.uniform(0.03, 0.07)
        direction = -1 if rng.random() < 0.5 else 1
        transformed = float(value) * (1 + direction * magnitude)
        return round(transformed, 2) if isinstance(value, float) else round(transformed)
    if isinstance(value, str) and not value.startswith("="):
        return re.sub(
            r"\b(19|20)\d{2}\b",
            lambda match: str(int(match.group(0)) - 1),
            value,
        )
    return value


def build_spreadsheet_n2_pair(
    task: SpreadsheetTask,
    output_path: str | Path,
    seed: int,
) -> SpreadsheetNoiseResult:
    output, workbook = _prepare_output(task, output_path)
    source = _source_sheet(workbook, task, seed)
    copied = workbook.copy_worksheet(source)
    copied.title = _available_title(workbook, _prior_title(source.title))
    copied.sheet_properties.tabColor = source.sheet_properties.tabColor
    for row in copied.iter_rows():
        for cell in row:
            cell_seed = int.from_bytes(
                hashlib.sha256(
                    f"{seed}:{source.title}:{cell.coordinate}".encode("utf-8")
                ).digest()[:8],
                "big",
            )
            cell.value = _prior_value(cell.value, random.Random(cell_seed))
    added_sheet = copied.title
    workbook.save(output)
    workbook.close()
    return SpreadsheetNoiseResult(
        output_path=output,
        operator="spreadsheet_n2_unlabeled_stale_sheet",
        severity="L2",
        seed=seed,
        added_sheet=added_sheet,
        clean_hash=task.clean_hash,
        noisy_hash=sha256_file(output),
    )

