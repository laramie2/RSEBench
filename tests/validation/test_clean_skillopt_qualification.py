import json
from pathlib import Path

from scripts.build_clean_skillopt_qualification import (
    build_clean_skillopt_qualification,
    build_officeqa_clean_split,
    build_spreadsheet_clean_split,
)


SHARED_ROOT = Path(__file__).resolve().parents[4]
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
