from __future__ import annotations

import json
from pathlib import Path

from rsebench.skillflow.contracts import SkillFlowInputManifest
from scripts.build_skillflow_clean_manifest import build_manifest


ROOT = Path(__file__).parents[2]


def test_builder_freezes_exact_skillflow_candidate_batches(tmp_path: Path) -> None:
    output = tmp_path / "input_manifest.json"

    first = build_manifest(
        config_path=ROOT / "configs/experiments/skillflow-clean-qualification-v1.yaml",
        data_root=ROOT / "data/raw/skillflow_tasks/test_tasks",
        output_path=output,
    )
    first_bytes = output.read_bytes()
    second = build_manifest(
        config_path=ROOT / "configs/experiments/skillflow-clean-qualification-v1.yaml",
        data_root=ROOT / "data/raw/skillflow_tasks/test_tasks",
        output_path=output,
    )

    assert first == second
    assert output.read_bytes() == first_bytes
    manifest = SkillFlowInputManifest.model_validate_json(output.read_text())
    assert manifest.batch_a == [
        "Document-Fraud-Detection",
        "Operational-Recovery-Planning",
        "HWPX-Document-Automation",
        "SEC-13F-Financial-Analysis",
    ]
    assert manifest.batch_b == [
        "OCR-Data-Extraction",
        "Cross-Format-Data-Reconciliation",
    ]
    assert sum(len(family.tasks) for family in manifest.families) == 48
    statuses = {family.family: family.status for family in manifest.families}
    assert statuses["Operational-Recovery-Planning"] == "invalid"
    assert all(
        status == "ready"
        for family, status in statuses.items()
        if family != "Operational-Recovery-Planning"
    )
    invalid = next(
        family
        for family in manifest.families
        if family.family == "Operational-Recovery-Planning"
    )
    assert invalid.invalid_reasons == [
        "ranking_missing_task:new_task_4_authorization_review_recovery"
    ]
    assert manifest.provider_calls == 0
    assert json.loads(output.read_text())["replicates"] == ["r1", "r2", "r3"]
