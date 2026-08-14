#!/usr/bin/env python3
"""Freeze clean-only SpreadsheetBench and OfficeQA SkillOpt manifests."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SHARED_ROOT = (
    PROJECT_ROOT.parents[1] if ".worktrees" in PROJECT_ROOT.parts else PROJECT_ROOT
)
DATA_ROOT = Path(os.environ.get("RSEBENCH_DATA_ROOT", SHARED_ROOT / "data")).resolve()
METHODS_ROOT = Path(
    os.environ.get("RSEBENCH_METHODS_ROOT", SHARED_ROOT / "methods/external")
).resolve()
OUTPUT_ROOT = PROJECT_ROOT / "benchmark/validation/clean_qualification_v1"
OUTPUT_ROOT_V2 = PROJECT_ROOT / "benchmark/validation/clean_qualification_v2"
METHOD_SEEDS = (20260813, 20260814, 20260815)


from rsebench.core1.dataset import (  # noqa: E402
    make_clean_split_paths_portable,
    rehash_task,
)
from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
)
from rsebench.evolution.calibration import freeze_officeqa_pilot  # noqa: E402
from rsebench.generation import _load_evolution_tasks  # noqa: E402
from rsebench.hashing import sha256_file  # noqa: E402
from scripts.build_core1_splits import _office_task  # noqa: E402


def _build_split(
    *,
    benchmark: str,
    domain: str,
    train: list,
    validation: list,
    clean_test: list,
    metadata: dict[str, Any],
    seed: int,
) -> CleanEvolutionSplitManifest:
    payload = {
        "benchmark": benchmark,
        "domain": domain,
        "seed": seed,
        "train": [task.model_dump(mode="json") for task in train],
        "validation": [task.model_dump(mode="json") for task in validation],
        "clean_test": [task.model_dump(mode="json") for task in clean_test],
        "metadata": metadata,
    }
    return CleanEvolutionSplitManifest(
        benchmark=benchmark,
        domain=domain,
        seed=seed,
        source_hash=canonical_hash(payload),
        train=train,
        validation=validation,
        clean_test=clean_test,
        metadata=metadata,
    )


def build_spreadsheet_clean_split() -> CleanEvolutionSplitManifest:
    source = json.loads(
        (DATA_ROOT / "splits/spreadsheetbench_verified/split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    train_ids = source["evolution"][:20]
    validation_ids = source["validation"][:10]
    test_ids = source["test"][:30]
    ordered_ids = train_ids + validation_ids + test_ids
    loaded = _load_evolution_tasks(
        {
            "benchmark": "spreadsheetbench_verified",
            "dataset_path": (
                "materialized/spreadsheetbench_verified/spreadsheetbench_verified_400"
            ),
        },
        DATA_ROOT,
        ordered_ids,
    )
    tasks = {
        task.task_id: rehash_task(
            task, artifact_hash=sha256_file(task.artifact_path or "")
        )
        for task in loaded
    }
    metadata = {
        "config_version": "clean-qualification-v1",
        "qualification_version": "clean-qualification-v1",
        "baseline": "skillopt",
        "source_partition": {
            "train": "evolution",
            "validation": "validation",
            "clean_test": "test",
        },
        "runtime": {
            "max_steps": 3,
            "batch_size": 7,
            "workers": 2,
            "max_tool_turns": 3,
            "max_completion_tokens": 2048,
        },
    }
    return _build_split(
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        train=[tasks[task_id] for task_id in train_ids],
        validation=[tasks[task_id] for task_id in validation_ids],
        clean_test=[tasks[task_id] for task_id in test_ids],
        metadata=metadata,
        seed=int(source["seed"]),
    )


def build_officeqa_clean_split() -> CleanEvolutionSplitManifest:
    source = json.loads(
        (DATA_ROOT / "splits/officeqa_calibrated/split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    frame = pd.read_csv(DATA_ROOT / "materialized/officeqa_full/officeqa_full.csv")
    rows = {str(row.uid): row for row in frame.itertuples(index=False)}
    eligibility = source["evidence_eligibility"]
    parsed_root = DATA_ROOT / "materialized/officeqa_full/parsed"

    def task(task_id: str):
        base = _office_task(rows[task_id])
        evidence = dict(eligibility[task_id])
        metadata = {
            **base.metadata,
            "evidence_eligibility": evidence,
            "external_evidence_required": not bool(evidence["eligible"]),
            "parsed_page_root_path": str(parsed_root),
            "scorer": "officeqa_released_numeric_v1",
            "scorer_tolerance": 0.01,
        }
        return rehash_task(base.model_copy(update={"metadata": metadata}))

    train = [task(task_id) for task_id in source["evolution"]]
    validation = [task(task_id) for task_id in source["validation"]]
    clean_test = [task(task_id) for task_id in source["test"]]
    metadata = {
        "config_version": "clean-qualification-v1",
        "qualification_version": "clean-qualification-v1",
        "baseline": "skillopt",
        "calibrated_source_hash": source["source_hash"],
        "source_partition": {
            "train": "evolution",
            "validation": "validation",
            "clean_test": "test",
        },
        "runtime": {
            "max_steps": 3,
            "batch_size": 4,
            "workers": 2,
            "max_tool_turns": 12,
            "max_completion_tokens": 4096,
        },
        "qualification_policy": {
            "min_parseable_answer_rate": 0.80,
            "max_systemic_failure_rate": 0.05,
        },
        "scorer": {
            "name": "officeqa_released_numeric_v1",
            "relative_numeric_tolerance": 0.01,
        },
    }
    return _build_split(
        benchmark="officeqa_full",
        domain="document",
        train=train,
        validation=validation,
        clean_test=clean_test,
        metadata=metadata,
        seed=int(source["seed"]),
    )


def build_officeqa_clean_split_v2() -> CleanEvolutionSplitManifest:
    """Build the audited OfficeQA qualification amendment.

    V1's six-task validation slice contained UID0240, whose prompt does not
    identify a face value or maturity and is therefore underdetermined under
    the zero-coupon equations it asks the agent to use. Removing that task
    before replaying the original seeded stratified selection both preserves
    the predeclared selection rule and provides a larger, lower-variance
    validation gate.
    """

    source = json.loads(
        (DATA_ROOT / "splits/officeqa_calibrated/split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    frame = pd.read_csv(DATA_ROOT / "materialized/officeqa_full/officeqa_full.csv")
    row_records = frame.to_dict(orient="records")
    amended_rows = [row for row in row_records if str(row["uid"]) != "UID0240"]
    amended = freeze_officeqa_pilot(
        amended_rows,
        source["calibration"],
        seed=int(source["seed"]),
        train_size=12,
        validation_size=12,
        test_size=20,
    )
    tuple_rows = {str(row.uid): row for row in frame.itertuples(index=False)}
    parsed_root = DATA_ROOT / "materialized/officeqa_full/parsed"

    def task(task_id: str):
        base = _office_task(tuple_rows[task_id])
        evidence = amended.evidence_eligibility[task_id].model_dump(mode="json")
        metadata = {
            **base.metadata,
            "evidence_eligibility": evidence,
            "external_evidence_required": not bool(evidence["eligible"]),
            "parsed_page_root_path": str(parsed_root),
            "scorer": "officeqa_released_numeric_v1",
            "scorer_tolerance": 0.01,
        }
        return rehash_task(base.model_copy(update={"metadata": metadata}))

    metadata = {
        "config_version": "clean-qualification-v2",
        "qualification_version": "clean-qualification-v2",
        "baseline": "skillopt",
        "calibrated_source_hash": source["source_hash"],
        "amended_source_hash": amended.source_hash,
        "source_partition": {
            "train": "amended_stratified_evolution",
            "validation": "amended_stratified_validation",
            "clean_test": "amended_stratified_test",
        },
        "runtime": {
            "max_steps": 3,
            "batch_size": 4,
            "workers": 2,
            "max_tool_turns": 12,
            "max_completion_tokens": 4096,
        },
        "qualification_policy": {
            "min_parseable_answer_rate": 0.80,
            "max_systemic_failure_rate": 0.05,
        },
        "qualification_amendment": {
            "supersedes": "clean-qualification-v1",
            "excluded_task_ids": ["UID0240"],
            "exclusion_reason": "mathematically_underdetermined_prompt",
            "selection_policy": "same_seed_stratified_prefix_without_excluded_tasks",
            "validation_size": 12,
        },
        "scorer": {
            "name": "officeqa_released_numeric_v1",
            "primary_metric": "hard",
            "relative_numeric_tolerance": 0.01,
        },
    }
    return _build_split(
        benchmark="officeqa_full",
        domain="document",
        train=[task(task_id) for task_id in amended.evolution],
        validation=[task(task_id) for task_id in amended.validation],
        clean_test=[task(task_id) for task_id in amended.test],
        metadata=metadata,
        seed=int(source["seed"]),
    )


def build_spreadsheet_clean_split_v2() -> CleanEvolutionSplitManifest:
    """Version the already-valid Spreadsheet split without changing sampling."""

    v1 = build_spreadsheet_clean_split()
    metadata = json.loads(json.dumps(v1.metadata))
    metadata.update(
        {
            "config_version": "clean-qualification-v2",
            "qualification_version": "clean-qualification-v2",
            "qualification_amendment": {
                "supersedes": "clean-qualification-v1",
                "sampling_changed": False,
                "reason": "control_plane_identity_timing_and_isolation",
            },
        }
    )
    payload = {
        "benchmark": v1.benchmark,
        "domain": v1.domain,
        "seed": v1.seed,
        "train": [task.model_dump(mode="json") for task in v1.train],
        "validation": [task.model_dump(mode="json") for task in v1.validation],
        "clean_test": [task.model_dump(mode="json") for task in v1.clean_test],
        "metadata": metadata,
    }
    return v1.model_copy(
        update={"source_hash": canonical_hash(payload), "metadata": metadata}
    )


def _serialize(payload: Any) -> bytes:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_immutable(path: Path, payload: Any) -> Path:
    encoded = _serialize(payload)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"different clean manifest already exists: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return path


def build_clean_skillopt_qualification(
    *, output_root: Path = OUTPUT_ROOT
) -> dict[str, Path]:
    local_splits = {
        "spreadsheetbench_verified": build_spreadsheet_clean_split(),
        "officeqa_full": build_officeqa_clean_split(),
    }
    outputs: dict[str, Path] = {}
    portable_splits: dict[str, CleanEvolutionSplitManifest] = {}
    for benchmark, split in local_splits.items():
        portable = make_clean_split_paths_portable(
            split,
            project_root=PROJECT_ROOT,
            data_root=DATA_ROOT,
            methods_root=METHODS_ROOT,
        )
        portable_splits[benchmark] = portable
        outputs[benchmark] = _write_immutable(
            output_root / f"{benchmark}.json", portable
        )
    index = {
        "schema_version": "rsebench.clean-skillopt-manifest.v1",
        "config_version": "clean-qualification-v1",
        "method_seeds": list(METHOD_SEEDS),
        "outputs": {
            benchmark: {
                "path": path.relative_to(output_root).as_posix(),
                "sizes": {
                    "train": len(portable_splits[benchmark].train),
                    "validation": len(portable_splits[benchmark].validation),
                    "clean_test": len(portable_splits[benchmark].clean_test),
                },
                "source_hash": portable_splits[benchmark].source_hash,
            }
            for benchmark, path in outputs.items()
        },
    }
    _write_immutable(output_root / "skillopt_manifest.json", index)
    return outputs


def build_clean_skillopt_qualification_v2(
    *, output_root: Path = OUTPUT_ROOT_V2
) -> dict[str, Path]:
    """Materialize both canonical SkillOpt clean-v2 cells."""

    local_splits = {
        "spreadsheetbench_verified": build_spreadsheet_clean_split_v2(),
        "officeqa_full": build_officeqa_clean_split_v2(),
    }
    portable_splits = {
        benchmark: make_clean_split_paths_portable(
            split,
            project_root=PROJECT_ROOT,
            data_root=DATA_ROOT,
            methods_root=METHODS_ROOT,
        )
        for benchmark, split in local_splits.items()
    }
    outputs = {
        benchmark: _write_immutable(
            output_root / f"{benchmark}.json", portable
        )
        for benchmark, portable in portable_splits.items()
    }
    index = {
        "schema_version": "rsebench.clean-skillopt-manifest.v1",
        "config_version": "clean-qualification-v2",
        "method_seeds": list(METHOD_SEEDS),
        "outputs": {
            benchmark: {
                "path": outputs[benchmark].relative_to(output_root).as_posix(),
                "sizes": {
                    "train": len(portable_splits[benchmark].train),
                    "validation": len(portable_splits[benchmark].validation),
                    "clean_test": len(portable_splits[benchmark].clean_test),
                },
                "source_hash": portable_splits[benchmark].source_hash,
            }
            for benchmark in local_splits
        },
    }
    _write_immutable(output_root / "skillopt_manifest.json", index)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--qualification-version", choices=("v1", "v2"), default="v1"
    )
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.qualification_version == "v2":
        outputs = build_clean_skillopt_qualification_v2(
            output_root=args.output_root or OUTPUT_ROOT_V2
        )
    else:
        outputs = build_clean_skillopt_qualification(
            output_root=args.output_root or OUTPUT_ROOT
        )
    print(json.dumps({key: str(path) for key, path in outputs.items()}, indent=2))


if __name__ == "__main__":
    main()
