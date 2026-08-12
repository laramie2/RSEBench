"""Bridge RSEBench paired manifests into SkillOpt's native split layouts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from rsebench.contracts import TaskManifest
from rsebench.evolution.contracts import EvolutionSplitManifest


Arm = Literal["clean", "noisy"]


def _spreadsheet_item(task: TaskManifest) -> dict:
    artifact = Path(task.artifact_path or "")
    if not artifact.is_file():
        raise FileNotFoundError(
            f"spreadsheet artifact missing for {task.task_id}: {artifact}"
        )
    metadata = task.metadata
    return {
        "id": task.task_id,
        "instruction": task.prompt,
        "instruction_type": str(metadata.get("instruction_type", "")),
        "answer_position": str(metadata.get("answer_range", "")),
        "answer_sheet": str(metadata.get("answer_sheet", "")),
        "spreadsheet_path": str(artifact.resolve().parent),
        "rsebench_source_hash": task.source_hash,
    }


def _officeqa_item(task: TaskManifest) -> dict:
    metadata = task.metadata
    source_files = [
        Path(str(value)).name for value in metadata.get("gold_document_ids", [])
    ]
    expected_gold_rank: int | None = None
    retrieval_fixture = str(metadata.get("retrieval_fixture") or "").strip()
    if retrieval_fixture:
        fixture_path = Path(retrieval_fixture)
        if not fixture_path.is_file():
            raise FileNotFoundError(
                f"OfficeQA retrieval fixture missing for {task.task_id}: {fixture_path}"
            )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        ranked = [
            Path(str(row.get("document_id") or "")).name
            for row in fixture.get("results", [])
            if str(row.get("document_id") or "").strip()
        ]
        if not ranked:
            raise ValueError(f"OfficeQA retrieval fixture is empty: {fixture_path}")
        source_files = ranked
        expected_gold_rank = int(fixture.get("expected_gold_rank") or 0) or None
    item = {
        "id": task.task_id,
        "uid": task.task_id,
        "question": task.prompt,
        "ground_truth": task.gold_answers[0] if task.gold_answers else "",
        "category": str(metadata.get("category", "officeqa")),
        "source_files": source_files,
        "source_docs": list(metadata.get("source_docs", [])),
        "split": str(metadata.get("source_split", "")),
        "rsebench_source_hash": task.source_hash,
    }
    if expected_gold_rank is not None:
        item["rsebench_expected_gold_rank"] = expected_gold_rank
    return item


def _livemath_item(task: TaskManifest) -> dict:
    metadata = task.metadata
    choices = list(metadata.get("choices", []))
    correct = dict(metadata.get("correct_choice", {}))
    if not choices or not correct.get("label"):
        raise ValueError(
            f"LiveMathematicianBench task lacks choices or label: {task.task_id}"
        )
    return {
        "id": task.task_id,
        "month": str(metadata.get("month", "")),
        "no": metadata.get("no", task.task_id),
        "paper_link": str(metadata.get("paper_link", "")),
        "theorem": str(metadata.get("theorem", "")),
        "sketch": str(metadata.get("sketch", "")),
        "theorem_type": list(metadata.get("theorem_type", [])),
        "question": task.prompt,
        "choices": choices,
        "correct_choice": correct,
        "source_path": str(metadata.get("source_path", "")),
        "rsebench_source_hash": task.source_hash,
    }


def _dapo_item(task: TaskManifest) -> dict:
    metadata = task.metadata
    if not task.gold_answers or not str(task.gold_answers[0]).strip():
        raise ValueError(f"DAPO task lacks a ground-truth answer: {task.task_id}")
    return {
        "id": task.task_id,
        "question": task.prompt,
        "ground_truth": str(task.gold_answers[0]),
        "task_type": str(metadata.get("ability", "MATH")),
        "reward_style": str(metadata.get("reward_style", "rule-lighteval/MATH_v2")),
        "rsebench_source_hash": task.source_hash,
    }


def _docvqa_item(task: TaskManifest) -> dict:
    image = Path(task.artifact_path or "")
    if not image.is_file():
        raise FileNotFoundError(f"DocVQA image missing for {task.task_id}: {image}")
    metadata = task.metadata
    question_types = [
        str(value) for value in metadata.get("question_types", []) if str(value)
    ]
    task_type = question_types[0] if question_types else "docvqa"
    return {
        "id": task.task_id,
        "questionId": task.task_id,
        "question": task.prompt,
        "answer": task.gold_answers[0] if task.gold_answers else "",
        "answers": list(task.gold_answers),
        "task_type": task_type,
        "subtask": task_type,
        "image_path": str(image.resolve()),
        "image_paths": [str(image.resolve())],
        "docId": str(metadata.get("doc_id", "")),
        "ucsf_document_id": str(metadata.get("ucsf_document_id", "")),
        "ucsf_document_page_no": str(metadata.get("ucsf_document_page_no", "")),
        "source_split": str(metadata.get("source_split", "")),
        "rsebench_source_hash": task.source_hash,
    }


def _searchqa_item(task: TaskManifest) -> dict:
    context = str(task.metadata.get("context") or "").strip()
    if not context:
        raise ValueError(f"SearchQA task lacks grounded context: {task.task_id}")
    if not task.gold_answers:
        raise ValueError(f"SearchQA task lacks answers: {task.task_id}")
    return {
        "id": task.task_id,
        "question": task.prompt,
        "context": context,
        "answers": list(task.gold_answers),
        "task_type": "qa",
        "rsebench_source_hash": task.source_hash,
    }


def _native_item(task: TaskManifest) -> dict:
    if task.benchmark == "spreadsheetbench_verified":
        return _spreadsheet_item(task)
    if task.benchmark == "officeqa_full":
        return _officeqa_item(task)
    if task.benchmark == "livemathematicianbench":
        return _livemath_item(task)
    if task.benchmark == "dapo_fixed_1000":
        return _dapo_item(task)
    if task.benchmark == "docvqa_10pct":
        return _docvqa_item(task)
    if task.benchmark == "searchqa_skillopt":
        return _searchqa_item(task)
    raise ValueError(f"SkillOpt bridge does not support {task.benchmark}")


def materialize_skillopt_split(
    split: EvolutionSplitManifest,
    *,
    arm: Arm,
    output_dir: Path | str,
) -> Path:
    """Write an arm-specific train/val and shared clean test split for SkillOpt."""
    if arm not in {"clean", "noisy"}:
        raise ValueError(f"unknown evolution arm: {arm}")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    pair_splits = {"train": split.train, "val": split.validation}
    audit: dict[str, object] = {
        "benchmark": split.benchmark,
        "arm": arm,
        "source_split_hash": split.source_hash,
        "splits": {},
    }
    for split_name, pairs in pair_splits.items():
        tasks = [getattr(pair, arm) for pair in pairs]
        items = [_native_item(task) for task in tasks]
        split_dir = root / split_name
        split_dir.mkdir()
        (split_dir / "items.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        audit["splits"][split_name] = [task.source_hash for task in tasks]

    test_items = [_native_item(task) for task in split.clean_test]
    test_dir = root / "test"
    test_dir.mkdir()
    (test_dir / "items.json").write_text(
        json.dumps(test_items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    audit["splits"]["test"] = [task.source_hash for task in split.clean_test]
    (root / "rsebench_materialization.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def materialize_skillopt_clean_test(
    clean_test: list[TaskManifest], *, output_dir: Path | str
) -> Path:
    """Write a test-only SkillOpt split without introducing evaluation noise."""
    if not clean_test:
        raise ValueError("clean test split must be non-empty")
    benchmarks = {task.benchmark for task in clean_test}
    if len(benchmarks) != 1:
        raise ValueError("clean test tasks must use one benchmark")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    for split_name in ("train", "val"):
        split_dir = root / split_name
        split_dir.mkdir()
        (split_dir / "items.json").write_text("[]\n", encoding="utf-8")
    test_dir = root / "test"
    test_dir.mkdir()
    (test_dir / "items.json").write_text(
        json.dumps(
            [_native_item(task) for task in clean_test],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "rsebench_materialization.json").write_text(
        json.dumps(
            {
                "benchmark": next(iter(benchmarks)),
                "arm": "clean_test_only",
                "splits": {
                    "train": [],
                    "val": [],
                    "test": [task.source_hash for task in clean_test],
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root
