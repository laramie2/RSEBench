import json
from pathlib import Path

from scripts.build_clean_skillopt_qualification import (
    build_clean_skillopt_qualification,
    build_clean_skillopt_qualification_v2,
    build_officeqa_clean_split,
    build_officeqa_clean_split_v2,
    build_spreadsheet_clean_split,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_ROOT = (
    PROJECT_ROOT.parents[1] if ".worktrees" in PROJECT_ROOT.parts else PROJECT_ROOT
)
DATA_ROOT = SHARED_ROOT / "data"


def test_clean_skillopt_splits_use_confirmation_scale_locked_budgets() -> None:
    spreadsheet = build_spreadsheet_clean_split()
    assert (
        len(spreadsheet.train),
        len(spreadsheet.validation),
        len(spreadsheet.clean_test),
    ) == (20, 10, 30)
    assert spreadsheet.metadata["runtime"] == {
        "max_steps": 3,
        "batch_size": 7,
        "workers": 2,
        "max_tool_turns": 3,
        "max_completion_tokens": 2048,
    }

    office = build_officeqa_clean_split()
    assert (
        len(office.train),
        len(office.validation),
        len(office.clean_test),
    ) == (12, 6, 20)
    assert office.metadata["runtime"] == {
        "max_steps": 3,
        "batch_size": 4,
        "workers": 2,
        "max_tool_turns": 12,
        "max_completion_tokens": 4096,
    }
    assert office.metadata["qualification_policy"] == {
        "min_parseable_answer_rate": 0.80,
        "max_systemic_failure_rate": 0.05,
    }

    for split in (spreadsheet, office):
        tasks = split.train + split.validation + split.clean_test
        assert len({task.task_id for task in tasks}) == len(tasks)
        assert "noisy" not in split.model_dump_json()


def test_clean_skillopt_splits_preserve_frozen_source_order() -> None:
    spreadsheet_source = json.loads(
        (DATA_ROOT / "splits/spreadsheetbench_verified/split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    spreadsheet = build_spreadsheet_clean_split()
    assert [task.task_id for task in spreadsheet.train] == spreadsheet_source[
        "evolution"
    ][:20]
    assert [task.task_id for task in spreadsheet.validation] == spreadsheet_source[
        "validation"
    ][:10]
    assert [task.task_id for task in spreadsheet.clean_test] == spreadsheet_source[
        "test"
    ][:30]

    office_source = json.loads(
        (DATA_ROOT / "splits/officeqa_calibrated/split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    office = build_officeqa_clean_split()
    assert [task.task_id for task in office.train] == office_source["evolution"]
    assert [task.task_id for task in office.validation] == office_source["validation"]
    assert [task.task_id for task in office.clean_test] == office_source["test"]
    assert all("evidence_eligibility" in task.metadata for task in office.train)
    assert all(task.metadata["scorer_tolerance"] == 0.01 for task in office.clean_test)


def test_officeqa_v2_replaces_invalid_ceiling_sample_and_expands_validation() -> None:
    office = build_officeqa_clean_split_v2()
    train_ids = [task.task_id for task in office.train]
    validation_ids = [task.task_id for task in office.validation]
    test_ids = [task.task_id for task in office.clean_test]

    assert (len(train_ids), len(validation_ids), len(test_ids)) == (12, 12, 20)
    assert train_ids == [
        "UID0040", "UID0076", "UID0198", "UID0071", "UID0244", "UID0140",
        "UID0080", "UID0088", "UID0126", "UID0207", "UID0224", "UID0155",
    ]
    assert validation_ids == [
        "UID0176", "UID0137", "UID0070", "UID0027", "UID0068", "UID0135",
        "UID0145", "UID0129", "UID0219", "UID0085", "UID0112", "UID0206",
    ]
    assert "UID0240" not in train_ids + validation_ids + test_ids
    assert len(set(train_ids + validation_ids + test_ids)) == 44
    assert office.metadata["qualification_amendment"] == {
        "supersedes": "clean-qualification-v1",
        "excluded_task_ids": ["UID0240"],
        "exclusion_reason": "mathematically_underdetermined_prompt",
        "selection_policy": "same_seed_stratified_prefix_without_excluded_tasks",
        "validation_size": 12,
    }
    assert office.metadata["scorer"]["primary_metric"] == "hard"


def test_clean_skillopt_materialization_is_portable_and_byte_stable(
    tmp_path: Path,
) -> None:
    first = build_clean_skillopt_qualification(output_root=tmp_path)
    first_bytes = {name: path.read_bytes() for name, path in first.items()}

    second = build_clean_skillopt_qualification(output_root=tmp_path)

    assert first == second
    assert {name: path.read_bytes() for name, path in second.items()} == first_bytes
    for path in first.values():
        raw = path.read_text(encoding="utf-8")
        assert "/home/" not in raw
        assert '"noisy"' not in raw
    index = json.loads(
        (tmp_path / "skillopt_manifest.json").read_text(encoding="utf-8")
    )
    assert index["method_seeds"] == [20260813, 20260814, 20260815]


def test_officeqa_v2_materialization_is_portable_and_byte_stable(
    tmp_path: Path,
) -> None:
    first = build_clean_skillopt_qualification_v2(output_root=tmp_path)
    first_bytes = {name: path.read_bytes() for name, path in first.items()}
    second = build_clean_skillopt_qualification_v2(output_root=tmp_path)

    assert first == second
    assert {name: path.read_bytes() for name, path in second.items()} == first_bytes
    raw = first["officeqa_full"].read_text(encoding="utf-8")
    assert "/home/" not in raw
    payload = json.loads(raw)
    task_ids = [
        task["task_id"]
        for partition in ("train", "validation", "clean_test")
        for task in payload[partition]
    ]
    assert "UID0240" not in task_ids
    index = json.loads((tmp_path / "skillopt_manifest.json").read_text())
    assert index["config_version"] == "clean-qualification-v2"
    assert index["outputs"]["officeqa_full"]["sizes"] == {
        "train": 12,
        "validation": 12,
        "clean_test": 20,
    }
