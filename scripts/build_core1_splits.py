#!/usr/bin/env python3
"""Materialize the four real Core-1 paired datasets used by validation runs."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from rsebench.contracts import TaskManifest
from rsebench.core1.dataset import (
    build_core1_pair,
    build_core1_split,
    make_split_paths_portable,
    rehash_task,
)
from rsebench.core1.materialize import (
    Core1NoiseProfile,
    load_core1_noise_profile,
    materialize_core1_profile,
)
from rsebench.core1.officeqa import (
    build_conflicting_period_fixture,
    build_officeqa_n1_pair,
    select_structurally_calibrated_tasks,
)
from rsebench.core1.skilllearn import (
    build_skilllearn_n1_pair,
    build_skilllearn_n2_pair,
)
from rsebench.core1.spreadsheet import (
    build_spreadsheet_n1_pair,
    build_spreadsheet_n2_pair,
)
from rsebench.domains.officeqa import CorpusDocument, OfficeQATask
from rsebench.domains.spreadsheet import SpreadsheetTask
from rsebench.evidence import canonical_hash, write_record
from rsebench.evolution.contracts import EvolutionTaskPair
from rsebench.generation import _load_evolution_tasks
from rsebench.hashing import sha256_file, sha256_tree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = PROJECT_ROOT.parents[1] if ".worktrees" in PROJECT_ROOT.parts else PROJECT_ROOT
DATA_ROOT = Path(os.environ.get("RSEBENCH_DATA_ROOT", SHARED_ROOT / "data")).resolve()
METHODS_ROOT = Path(
    os.environ.get("RSEBENCH_METHODS_ROOT", SHARED_ROOT / "methods/external")
).resolve()
SEED = 20260813
HARD_GATES = {
    "structural_valid": True,
    "label_invariant": True,
    "solvable": True,
    "answer_leak_free": True,
}


def _profile(benchmark: str, stage: str) -> Core1NoiseProfile:
    return load_core1_noise_profile(
        PROJECT_ROOT / "configs/core1" / benchmark / f"{stage}.yaml"
    )


def _write_split(split, benchmark: str, stage: str) -> Path:
    destination = (
        PROJECT_ROOT / "benchmark/core1/splits" / benchmark / f"{stage}.json"
    )
    portable = make_split_paths_portable(
        split,
        project_root=PROJECT_ROOT,
        data_root=DATA_ROOT,
        methods_root=METHODS_ROOT,
    )
    write_record(destination, portable)
    return destination


def _runtime_or_static_pair(
    *,
    profile: Core1NoiseProfile,
    clean: TaskManifest,
    noisy: TaskManifest | None = None,
    metadata: dict[str, Any] | None = None,
) -> EvolutionTaskPair:
    return build_core1_pair(
        clean=clean,
        noisy=noisy or clean,
        profile=profile,
        metadata={"hard_gates": HARD_GATES, **(metadata or {})},
    )


def _spreadsheet_native(task: TaskManifest) -> SpreadsheetTask:
    metadata = task.metadata
    return SpreadsheetTask.from_paths(
        task_id=task.task_id,
        workbook_path=task.artifact_path or "",
        gold_workbook_path=metadata.get("gold_workbook_path"),
        prompt=task.prompt,
        answer_sheet=str(metadata.get("answer_sheet", "")),
        answer_range=str(metadata.get("answer_range", "")),
    )


def build_spreadsheet() -> list[Path]:
    source_split = json.loads(
        (DATA_ROOT / "splits/spreadsheetbench_verified/split_manifest.json").read_text()
    )
    ids = (
        source_split["evolution"][:6]
        + source_split["validation"][:3]
        + source_split["test"][:10]
    )
    loaded = _load_evolution_tasks(
        {
            "benchmark": "spreadsheetbench_verified",
            "dataset_path": "materialized/spreadsheetbench_verified/spreadsheetbench_verified_400",
        },
        DATA_ROOT,
        ids,
    )
    tasks = {
        task.task_id: rehash_task(
            task, artifact_hash=sha256_file(task.artifact_path or "")
        )
        for task in loaded
    }
    train_ids = source_split["evolution"][:5]
    # The N3 calibration run recorded task 11842 as inapplicable because its
    # native rollout produced no workbook-write event. Applicability is a
    # legal stage-specific split gate (it does not inspect test performance),
    # so N3 replaces it with the next official evolution task.
    n3_train_ids = [
        task_id for task_id in source_split["evolution"] if task_id != "11842"
    ][:5]
    validation_ids = source_split["validation"][:3]
    test = [tasks[task_id] for task_id in source_split["test"][:10]]
    outputs: list[Path] = []
    for stage in ("N1", "N2", "N3", "N4"):
        profile = _profile("spreadsheetbench_verified", stage)
        stage_train_ids = n3_train_ids if stage == "N3" else train_ids

        def pair(task_id: str) -> EvolutionTaskPair:
            clean = tasks[task_id]
            if stage in {"N3", "N4"}:
                return _runtime_or_static_pair(profile=profile, clean=clean)
            native = _spreadsheet_native(clean)
            if stage == "N1":
                result = build_spreadsheet_n1_pair(native, SEED)
                noisy = rehash_task(
                    clean.model_copy(update={"prompt": result.noisy_prompt})
                )
                detail = {"changed_axis": result.changed_axis}
            else:
                artifact = (
                    PROJECT_ROOT
                    / "benchmark/core1/static_data/spreadsheetbench_verified/N2"
                    / task_id
                    / "noisy.xlsx"
                )
                result = build_spreadsheet_n2_pair(native, artifact, SEED)
                noisy = rehash_task(
                    clean.model_copy(update={"artifact_path": str(artifact.resolve())}),
                    artifact_hash=result.noisy_hash,
                )
                detail = {"added_sheet": result.added_sheet}
            return _runtime_or_static_pair(
                profile=profile, clean=clean, noisy=noisy, metadata=detail
            )

        split = build_core1_split(
            profile=profile,
            train=[pair(task_id) for task_id in stage_train_ids],
            validation=[pair(task_id) for task_id in validation_ids],
            clean_test=test,
        )
        outputs.append(_write_split(split, profile.benchmark, stage))
    return outputs


def _answers(value: object) -> list[str]:
    text = str(value)
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        parsed = None
    if isinstance(parsed, (list, tuple)):
        return [str(item) for item in parsed]
    return [text]


def _office_task(row: Any) -> TaskManifest:
    source_files = [
        value.strip() for value in str(row.source_files).splitlines() if value.strip()
    ]
    source_docs = [
        value.strip() for value in str(row.source_docs).splitlines() if value.strip()
    ]
    task = TaskManifest(
        task_id=str(row.uid),
        benchmark="officeqa_full",
        domain="document",
        prompt=str(row.question),
        gold_answers=_answers(row.answer),
        source_hash="0" * 64,
        metadata={
            "gold_document_ids": source_files,
            "source_docs": source_docs,
            "difficulty": str(row.difficulty),
            "source_file_count": len(source_files),
        },
    )
    return rehash_task(task)


def _near_period_documents(
    native: OfficeQATask, corpus_root: Path
) -> list[CorpusDocument]:
    paths_by_name = {
        path.name: path for path in corpus_root.rglob("*.txt") if path.is_file()
    }
    candidates: list[Path] = []
    for source in [native.gold_document_id, *native.source_document_ids]:
        match = re.search(r"((?:19|20)\d{2})_(\d{2})\.txt$", Path(source).name)
        if match is None:
            continue
        year, month = int(match.group(1)), match.group(2)
        for offset in (-1, 1, -2, 2, -5, 5, -10, 10):
            candidate = paths_by_name.get(f"treasury_bulletin_{year + offset}_{month}.txt")
            if candidate is not None and candidate not in candidates:
                candidates.append(candidate)
    return [
        CorpusDocument(
            document_id=path.relative_to(corpus_root).as_posix(),
            text=path.read_text(encoding="utf-8", errors="replace"),
            path=str(path),
        )
        for path in candidates
    ]


def _select_office(
    ids: list[str], rows: dict[str, Any], corpus_root: Path, count: int
) -> tuple[list[TaskManifest], dict[str, Any]]:
    selected: list[TaskManifest] = []
    fixtures: dict[str, Any] = {}
    candidates = select_structurally_calibrated_tasks(
        [_office_task(rows[task_id]) for task_id in ids], count=len(ids)
    )
    for task in candidates:
        task_id = task.task_id
        gold_ids = list(task.metadata["gold_document_ids"])
        if not gold_ids or len(gold_ids) > 2:
            continue
        native = OfficeQATask(
            task_id=task_id,
            question=task.prompt,
            answers=task.gold_answers,
            gold_document_id=gold_ids[0],
            source_document_ids=gold_ids[1:],
        )
        try:
            fixture = build_conflicting_period_fixture(
                native, _near_period_documents(native, corpus_root), SEED
            )
        except ValueError:
            continue
        selected.append(task)
        fixtures[task_id] = fixture
        if len(selected) == count:
            return selected, fixtures
    raise RuntimeError(f"OfficeQA found {len(selected)} applicable tasks; need {count}")


def build_officeqa() -> list[Path]:
    source_split = json.loads(
        (DATA_ROOT / "splits/officeqa_full/split_manifest.json").read_text()
    )
    frame = pd.read_csv(
        DATA_ROOT / "materialized/officeqa_full/officeqa_full.csv"
    )
    rows = {str(row.uid): row for row in frame.itertuples(index=False)}
    corpus_root = DATA_ROOT / "materialized/officeqa_full/corpus"
    # N2 has a domain-specific applicability gate (a real conflicting source
    # must exist). Do not let that gate constrain the task pool for N1/N3/N4.
    # Those stages use the structurally calibrated official splits directly.
    base_train = select_structurally_calibrated_tasks(
        [_office_task(rows[task_id]) for task_id in source_split["evolution"]],
        count=6,
    )
    base_validation = select_structurally_calibrated_tasks(
        [_office_task(rows[task_id]) for task_id in source_split["validation"]],
        count=3,
    )
    n2_train, train_fixtures = _select_office(
        source_split["evolution"], rows, corpus_root, 6
    )
    n2_validation, validation_fixtures = _select_office(
        source_split["validation"], rows, corpus_root, 3
    )
    fixtures = {**train_fixtures, **validation_fixtures}
    excluded = {
        task.task_id
        for task in base_train + base_validation + n2_train + n2_validation
    }
    test_candidates = [
        _office_task(rows[task_id])
        for task_id in source_split["test"]
        if task_id not in excluded
    ]
    test = select_structurally_calibrated_tasks(test_candidates, count=10)
    outputs: list[Path] = []
    for stage in ("N1", "N2", "N3", "N4"):
        profile = _profile("officeqa", stage)
        train = n2_train if stage == "N2" else base_train
        validation = n2_validation if stage == "N2" else base_validation

        def pair(task: TaskManifest) -> EvolutionTaskPair:
            if stage in {"N3", "N4"}:
                return _runtime_or_static_pair(profile=profile, clean=task)
            gold_ids = list(task.metadata["gold_document_ids"])
            native = OfficeQATask(
                task_id=task.task_id,
                question=task.prompt,
                answers=task.gold_answers,
                gold_document_id=gold_ids[0],
                source_document_ids=gold_ids[1:],
            )
            if stage == "N1":
                result = build_officeqa_n1_pair(native, SEED)
                noisy = rehash_task(
                    task.model_copy(update={"prompt": result.noisy_question})
                )
                detail = {"changed_axis": result.axis}
            else:
                fixture_path = (
                    PROJECT_ROOT
                    / "benchmark/core1/static_data/officeqa_full/N2"
                    / f"{task.task_id}.json"
                )
                fixture_path.parent.mkdir(parents=True, exist_ok=True)
                write_record(fixture_path, fixtures[task.task_id])
                metadata = dict(task.metadata)
                metadata["retrieval_fixture"] = str(fixture_path.resolve())
                metadata["retrieval_fixture_hash"] = fixtures[
                    task.task_id
                ].fixture_hash
                noisy = rehash_task(task.model_copy(update={"metadata": metadata}))
                detail = {
                    "expected_gold_rank": fixtures[task.task_id].expected_gold_rank
                }
            return _runtime_or_static_pair(
                profile=profile, clean=task, noisy=noisy, metadata=detail
            )

        split = build_core1_split(
            profile=profile,
            train=[pair(task) for task in train],
            validation=[pair(task) for task in validation],
            clean_test=test,
        )
        outputs.append(_write_split(split, profile.benchmark, stage))
    return outputs


def _skilllearn_task(instance: Path) -> TaskManifest:
    task = TaskManifest(
        task_id=instance.name,
        benchmark="skilllearnbench",
        domain="skill_learning",
        prompt=(instance / "instruction.md").read_text(encoding="utf-8"),
        verifier="skilllearn_hidden_test_v1",
        source_hash="0" * 64,
        artifact_path=str(instance.resolve()),
        metadata={
            "task_family": instance.parent.name,
            "official_instance_path": str(instance.resolve()),
        },
    )
    return rehash_task(task, artifact_hash=sha256_tree(instance / "environment"))


def build_skilllearn() -> list[Path]:
    # Chinese regulated verse produced reverse evolution in the calibration
    # family even on the clean arm, so it cannot identify robustness effects.
    # Use a structurally repeated spreadsheet-production family whose five
    # instances share a skill while keeping acquisition and held-out files
    # disjoint. This remains a SkillLearn skill-task evaluation rather than a
    # SpreadsheetBench task: the unit is one reusable family skill learned
    # from instance-1 and transferred to instances 2-5.
    family_name = "weighted-gdp-calculation"
    family = METHODS_ROOT / f"skilllearnbench/tasks/{family_name}"
    acquisition = family / f"{family_name}-1"
    tests = [family / f"{family_name}-{index}" for index in range(2, 6)]
    clean = _skilllearn_task(acquisition)
    clean_test = [_skilllearn_task(instance) for instance in tests]
    outputs: list[Path] = []
    noisy_instance = (
        PROJECT_ROOT
        / f"benchmark/core1/static_data/skilllearnbench/N2/{family_name}-1/instance"
    )
    if not noisy_instance.exists():
        build_skilllearn_n2_pair(acquisition, noisy_instance, SEED)
    for stage in ("N1", "N2", "N3", "N4"):
        profile = _profile("skilllearnbench", stage)
        if stage == "N1":
            result = build_skilllearn_n1_pair(acquisition, SEED)
            noisy = rehash_task(
                clean.model_copy(update={"prompt": result.noisy_instruction}),
                artifact_hash=sha256_tree(acquisition / "environment"),
            )
            detail = {"strategy": result.strategy}
        elif stage == "N2":
            noisy = rehash_task(
                clean.model_copy(update={"artifact_path": str(noisy_instance.resolve())}),
                artifact_hash=sha256_tree(noisy_instance / "environment"),
            )
            detail = {"competing_resource": True}
        else:
            noisy = clean
            detail = {}
        split = build_core1_split(
            profile=profile,
            train=[
                _runtime_or_static_pair(
                    profile=profile, clean=clean, noisy=noisy, metadata=detail
                )
            ],
            validation=[],
            clean_test=clean_test,
        )
        outputs.append(_write_split(split, profile.benchmark, stage))
    return outputs


def _ensure_webshop_source() -> dict[str, Any]:
    path = PROJECT_ROOT / "benchmark/core1/static_data/webshop/source.json"
    if not path.is_file():
        python = METHODS_ROOT / "webshop/.venv/bin/python"
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            [
                str(PROJECT_ROOT / "src"),
                str(METHODS_ROOT / "webshop"),
                environment.get("PYTHONPATH", ""),
            ]
        )
        subprocess.run(
            [
                str(python),
                str(PROJECT_ROOT / "scripts/export_core1_webshop_source.py"),
                "--output",
                str(path),
            ],
            cwd=METHODS_ROOT / "webshop",
            env=environment,
            check=True,
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _webshop_task(goal_idx: int, goal: dict[str, Any]) -> TaskManifest:
    task = TaskManifest(
        task_id=f"goal_{goal_idx}",
        benchmark="webshop",
        domain="interactive",
        prompt=str(goal["instruction_text"]),
        verifier="webshop_official_reward_v1",
        source_hash="0" * 64,
        metadata={
            "goal_idx": goal_idx,
            "target_asin": str(goal["asin"]),
            "query": str(goal["query"]),
        },
    )
    return rehash_task(task)


def build_webshop() -> list[Path]:
    source = _ensure_webshop_source()
    goals = source["goals"]
    tasks = {
        int(index): _webshop_task(int(index), goal) for index, goal in goals.items()
    }
    train_ids = [int(value) for value in source["train"]]
    validation_ids = [int(value) for value in source["validation"]]
    test = [tasks[int(value)] for value in source["test"]]
    outputs: list[Path] = []
    for stage in ("N1", "N2", "N3", "N4"):
        profile = _profile("webshop", stage)
        static_path = (
            PROJECT_ROOT / "benchmark/core1/static_data/webshop" / f"{stage}.json"
        )
        if stage in {"N1", "N2"}:
            write_record(static_path, source[stage])

        def pair(goal_idx: int) -> EvolutionTaskPair:
            clean = tasks[goal_idx]
            if stage == "N1":
                overlay = source["N1"]["goals"][str(goal_idx)]
                noisy = rehash_task(
                    clean.model_copy(update={"prompt": overlay["noisy_goal"]})
                )
                detail = {
                    "static_noise_path": str(static_path.resolve()),
                    "violated_constraint": overlay["violated_constraint"],
                }
            elif stage == "N2":
                overlay = source["N2"]["goals"][str(goal_idx)]
                metadata = dict(clean.metadata)
                metadata["static_overlay_hash"] = canonical_hash(overlay)
                noisy = rehash_task(clean.model_copy(update={"metadata": metadata}))
                detail = {
                    "static_noise_path": str(static_path.resolve()),
                    "promoted_product_id": overlay["promoted_product_id"],
                }
            else:
                noisy = clean
                detail = {}
            return _runtime_or_static_pair(
                profile=profile, clean=clean, noisy=noisy, metadata=detail
            )

        split = build_core1_split(
            profile=profile,
            train=[pair(goal_idx) for goal_idx in train_ids],
            validation=[pair(goal_idx) for goal_idx in validation_ids],
            clean_test=test,
        )
        outputs.append(_write_split(split, profile.benchmark, stage))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--domain",
        choices=("spreadsheet", "document", "skill_learning", "interactive", "all"),
        default="all",
    )
    args = parser.parse_args()
    for profile_path in sorted((PROJECT_ROOT / "configs/core1").glob("*/*.yaml")):
        materialize_core1_profile(
            profile_path, output_root=PROJECT_ROOT / "benchmark/core1"
        )
    builders = {
        "spreadsheet": build_spreadsheet,
        "document": build_officeqa,
        "skill_learning": build_skilllearn,
        "interactive": build_webshop,
    }
    selected = builders if args.domain == "all" else {args.domain: builders[args.domain]}
    outputs: list[Path] = []
    for name, builder in selected.items():
        built = builder()
        outputs.extend(built)
        print(
            json.dumps(
                {
                    "domain": name,
                    "splits": [path.relative_to(PROJECT_ROOT).as_posix() for path in built],
                }
            )
        )
    summary = {
        "schema_version": "rsebench.core1-materialization.v1",
        "seed": SEED,
        "profiles": 16,
        "generated_splits": len(outputs),
        "hard_gates": HARD_GATES,
        "outputs": [path.relative_to(PROJECT_ROOT).as_posix() for path in outputs],
    }
    write_record(PROJECT_ROOT / "benchmark/core1/materialization.json", summary)


if __name__ == "__main__":
    main()
