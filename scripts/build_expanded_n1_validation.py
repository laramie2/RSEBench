#!/usr/bin/env python3
"""Build the larger, validation-only N1 paired splits for four domains."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.contracts import TaskManifest  # noqa: E402
from rsebench.core1.dataset import (  # noqa: E402
    build_core1_pair,
    build_core1_split,
    make_split_paths_portable,
    rehash_task,
)
from rsebench.core1.officeqa import (  # noqa: E402
    build_officeqa_n1_pair,
    select_structurally_calibrated_tasks,
)
from rsebench.core1.skilllearn import build_skilllearn_n1_pair  # noqa: E402
from rsebench.core1.spreadsheet import build_spreadsheet_n1_pair  # noqa: E402
from rsebench.domains.officeqa import OfficeQATask  # noqa: E402
from rsebench.evidence import write_record  # noqa: E402
from rsebench.evolution.contracts import (  # noqa: E402
    EvolutionSplitManifest,
    EvolutionTaskPair,
)
from rsebench.generation import _load_evolution_tasks  # noqa: E402
from rsebench.hashing import sha256_file, sha256_tree  # noqa: E402
from scripts.build_core1_splits import (  # noqa: E402
    HARD_GATES,
    METHODS_ROOT,
    SEED,
    _office_task,
    _profile,
    _skilllearn_task,
    _spreadsheet_native,
    _webshop_task,
)


SHARED_ROOT = PROJECT_ROOT.parents[1] if ".worktrees" in PROJECT_ROOT.parts else PROJECT_ROOT
DATA_ROOT = SHARED_ROOT / "data"
EXPANDED_ROOT = PROJECT_ROOT / "benchmark/validation/n1_expanded"

# Ordered using only public structure and execution diversity. Calibration may
# retain four families, but no noisy-arm score is used to define this pool.
SKILLLEARN_CANDIDATE_FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
    "github-repo-analytics",
    "financial-analysis",
    "stock-data-visualization",
    "enterprise-information-search",
)


def _pair(
    clean: TaskManifest,
    noisy: TaskManifest,
    *,
    benchmark: str,
    metadata: dict[str, object],
) -> EvolutionTaskPair:
    return build_core1_pair(
        clean=clean,
        noisy=noisy,
        profile=_profile(benchmark, "N1"),
        metadata={"hard_gates": HARD_GATES, **metadata},
    )


def _portable_write(
    split: EvolutionSplitManifest,
    destination: Path,
) -> Path:
    portable = make_split_paths_portable(
        split,
        project_root=PROJECT_ROOT,
        data_root=DATA_ROOT,
        methods_root=METHODS_ROOT,
    )
    write_record(destination, portable)
    return destination


def _spreadsheet_split() -> EvolutionSplitManifest:
    source = json.loads(
        (DATA_ROOT / "splits/spreadsheetbench_verified/split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    train_ids = source["evolution"][:8]
    validation_ids = source["validation"][:4]
    test_ids = source["test"][:20]
    tasks = {
        task.task_id: rehash_task(
            task, artifact_hash=sha256_file(task.artifact_path or "")
        )
        for task in _load_evolution_tasks(
            {
                "benchmark": "spreadsheetbench_verified",
                "dataset_path": (
                    "materialized/spreadsheetbench_verified/"
                    "spreadsheetbench_verified_400"
                ),
            },
            DATA_ROOT,
            train_ids + validation_ids + test_ids,
        )
    }

    def make_pair(task_id: str) -> EvolutionTaskPair:
        clean = tasks[task_id]
        generated = build_spreadsheet_n1_pair(_spreadsheet_native(clean), SEED)
        noisy = rehash_task(clean.model_copy(update={"prompt": generated.noisy_prompt}))
        return _pair(
            clean,
            noisy,
            benchmark="spreadsheetbench_verified",
            metadata={"changed_axis": generated.changed_axis},
        )

    return build_core1_split(
        profile=_profile("spreadsheetbench_verified", "N1"),
        train=[make_pair(task_id) for task_id in train_ids],
        validation=[make_pair(task_id) for task_id in validation_ids],
        clean_test=[tasks[task_id] for task_id in test_ids],
    )


def _officeqa_split() -> EvolutionSplitManifest:
    source = json.loads(
        (DATA_ROOT / "splits/officeqa_full/split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    frame = pd.read_csv(DATA_ROOT / "materialized/officeqa_full/officeqa_full.csv")
    rows = {str(row.uid): row for row in frame.itertuples(index=False)}

    def select(partition: str, count: int) -> list[TaskManifest]:
        candidates = select_structurally_calibrated_tasks(
            [_office_task(rows[task_id]) for task_id in source[partition]],
            count=len(source[partition]),
        )
        selected: list[TaskManifest] = []
        for task in candidates:
            gold_ids = list(task.metadata["gold_document_ids"])
            if not gold_ids:
                continue
            native = OfficeQATask(
                task_id=task.task_id,
                question=task.prompt,
                answers=task.gold_answers,
                gold_document_id=gold_ids[0],
                source_document_ids=gold_ids[1:],
            )
            try:
                build_officeqa_n1_pair(native, SEED)
            except ValueError:
                continue
            selected.append(task)
            if len(selected) == count:
                return selected
        raise RuntimeError(
            f"OfficeQA {partition} has {len(selected)} N1-applicable tasks; need {count}"
        )

    train = select("evolution", 8)
    validation = select("validation", 4)
    excluded = {task.task_id for task in train + validation}
    # The untouched test split does not need N1 applicability, but uses the
    # same public structural selector and remains disjoint from acquisition.
    test = select_structurally_calibrated_tasks(
        [_office_task(rows[task_id]) for task_id in source["test"] if task_id not in excluded],
        count=20,
    )

    def make_pair(clean: TaskManifest) -> EvolutionTaskPair:
        gold_ids = list(clean.metadata["gold_document_ids"])
        native = OfficeQATask(
            task_id=clean.task_id,
            question=clean.prompt,
            answers=clean.gold_answers,
            gold_document_id=gold_ids[0],
            source_document_ids=gold_ids[1:],
        )
        generated = build_officeqa_n1_pair(native, SEED)
        noisy = rehash_task(
            clean.model_copy(update={"prompt": generated.noisy_question})
        )
        return _pair(
            clean,
            noisy,
            benchmark="officeqa",
            metadata={"changed_axis": generated.axis},
        )

    return build_core1_split(
        profile=_profile("officeqa", "N1"),
        train=[make_pair(task) for task in train],
        validation=[make_pair(task) for task in validation],
        clean_test=test,
    )


def _webshop_split() -> EvolutionSplitManifest:
    source_path = EXPANDED_ROOT / "webshop_candidates.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    selection = json.loads(
        (EXPANDED_ROOT / "webshop_validation_selection.json").read_text(
            encoding="utf-8"
        )
    )
    train_ids = [int(value) for value in source["train"]]
    validation_ids = [int(value) for value in selection["selected_ids"]]
    test_ids = [int(value) for value in source["test"]]
    tasks = {
        int(goal_idx): _webshop_task(int(goal_idx), goal)
        for goal_idx, goal in source["goals"].items()
    }

    def make_pair(goal_idx: int) -> EvolutionTaskPair:
        clean = tasks[goal_idx]
        overlay = source["N1"]["goals"][str(goal_idx)]
        noisy = rehash_task(clean.model_copy(update={"prompt": overlay["noisy_goal"]}))
        return _pair(
            clean,
            noisy,
            benchmark="webshop",
            metadata={
                "static_noise_path": str(source_path.resolve()),
                "violated_constraint": overlay["violated_constraint"],
            },
        )

    return build_core1_split(
        profile=_profile("webshop", "N1"),
        train=[make_pair(goal_idx) for goal_idx in train_ids],
        validation=[make_pair(goal_idx) for goal_idx in validation_ids],
        clean_test=[tasks[goal_idx] for goal_idx in test_ids],
    )


def _skilllearn_split(family_name: str) -> EvolutionSplitManifest:
    family_root = METHODS_ROOT / "skilllearnbench/tasks" / family_name
    instances = sorted(
        (path for path in family_root.iterdir() if path.is_dir()),
        key=lambda path: int(path.name.rsplit("-", 1)[1]),
    )
    if len(instances) < 5:
        raise ValueError(f"SkillLearn family {family_name} needs at least 5 instances")
    tasks = [_skilllearn_task(instance) for instance in instances[:5]]

    def make_pair(clean: TaskManifest, instance: Path) -> EvolutionTaskPair:
        generated = build_skilllearn_n1_pair(instance, SEED)
        noisy = rehash_task(
            clean.model_copy(update={"prompt": generated.noisy_instruction}),
            artifact_hash=sha256_tree(instance / "environment"),
        )
        return _pair(
            clean,
            noisy,
            benchmark="skilllearnbench",
            metadata={"strategy": generated.strategy},
        )

    return build_core1_split(
        profile=_profile("skilllearnbench", "N1"),
        train=[make_pair(tasks[index], instances[index]) for index in range(2)],
        validation=[make_pair(tasks[2], instances[2])],
        clean_test=tasks[3:5],
    )


def build_expanded_n1_validation(
    *, output_root: Path = EXPANDED_ROOT
) -> dict[str, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "spreadsheetbench_verified": _portable_write(
            _spreadsheet_split(), output_root / "spreadsheetbench_verified.json"
        ),
        "officeqa_full": _portable_write(
            _officeqa_split(), output_root / "officeqa_full.json"
        ),
        "webshop": _portable_write(_webshop_split(), output_root / "webshop.json"),
    }
    skilllearn_root = output_root / "skilllearnbench"
    for family_name in SKILLLEARN_CANDIDATE_FAMILIES:
        outputs[f"skilllearnbench/{family_name}"] = _portable_write(
            _skilllearn_split(family_name), skilllearn_root / f"{family_name}.json"
        )
    write_record(
        output_root / "manifest.json",
        {
            "schema_version": "rsebench.expanded-n1-validation.v1",
            "seed": SEED,
            "task_domain_sizes": {
                "spreadsheetbench_verified": [8, 4, 20],
                "officeqa_full": [8, 4, 20],
                "webshop": [5, 3, 10],
            },
            "skilllearn_family_sizes": [2, 1, 2],
            "skilllearn_candidates": list(SKILLLEARN_CANDIDATE_FAMILIES),
            "outputs": {
                key: path.relative_to(output_root).as_posix()
                for key, path in outputs.items()
            },
        },
    )
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=EXPANDED_ROOT)
    args = parser.parse_args()
    outputs = build_expanded_n1_validation(output_root=args.output_root)
    print(json.dumps({key: str(path) for key, path in outputs.items()}, indent=2))


if __name__ == "__main__":
    main()
