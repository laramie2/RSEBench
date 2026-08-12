from pathlib import Path
import os
import subprocess
import sys

from scripts.download.datasets import build_download_plan


def test_core_download_plan_contains_required_sources(tmp_path: Path):
    plan = build_download_plan(tmp_path)
    ids = {item.source_id for item in plan}
    assert "KAKA22/SpreadsheetBench" in ids
    assert "databricks/officeqa" in ids
    assert "lmms-lab/DocVQA" in ids
    assert "BytedTsinghua-SIA/DAPO-Math-17k" in ids
    assert "LiveMathematicianBench/LiveMathematicianBench" in ids


def test_gated_officeqa_data_is_scheduled_last(tmp_path: Path):
    """A gated-source failure must not poison later Hub transfers."""
    plan = build_download_plan(tmp_path)
    assert plan[-1].source_id == "databricks/officeqa"


def test_officeqa_public_evaluator_source_is_downloaded(tmp_path: Path):
    plan = build_download_plan(tmp_path)
    ids = {item.source_id for item in plan}
    assert "https://github.com/databricks/officeqa.git" in ids


def test_dataset_audit_runs_as_a_direct_script(tmp_path: Path):
    root = Path(__file__).parents[1]
    env = os.environ.copy()
    env["RSEBENCH_DATA_ROOT"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(root / "scripts/audit_datasets.py")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
