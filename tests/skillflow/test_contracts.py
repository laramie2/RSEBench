from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from rsebench.skillflow.contracts import SkillFlowInputManifest


HASH = "a" * 64


def _payload() -> dict:
    return {
        "schema_version": "rsebench.skillflow-input.v1",
        "benchmark": "skillflow_tasks",
        "baseline": "skillflow",
        "upstream_revision": "7b49ff5a7e26cd7706e959bfa0dba4746d18440d",
        "qualification_contract": "skillflow-clean-qualification-v1",
        "config_hash": HASH,
        "runtime": {
            "model": "deepseek-v4-flash",
            "thinking": "disabled",
            "temperature": 0.0,
            "max_turns": 30,
            "max_completion_tokens": 2048,
            "patch_temperature": 0.2,
            "patch_max_tokens": 8192,
            "patch_max_steps": 60,
            "patch_max_observation_chars": 3000,
            "docker_image": "skillflow/harbor-cli-base:ubuntu24.04",
            "arm_timeout_seconds": 21600,
        },
        "qualification": {
            "minimum_positive_replicates": 2,
            "minimum_nonnegative_replicates": 3,
            "minimum_patch_replicates": 3,
            "minimum_skill_use_replicates": 2,
            "require_positive_pooled_full_delta": True,
            "target_qualified_families": 2,
        },
        "batch_a": ["Document-Fraud-Detection"],
        "batch_b": ["OCR-Data-Extraction"],
        "replicates": ["r1", "r2", "r3"],
        "families": [
            {
                "family": "Document-Fraud-Detection",
                "status": "ready",
                "ranking_hash": HASH,
                "ranked_task_ids": ["first", "second"],
                "tasks": [
                    {
                        "task_id": "first",
                        "order": 1,
                        "relative_path": "Document-Fraud-Detection/first",
                        "task_hash": HASH,
                    },
                    {
                        "task_id": "second",
                        "order": 2,
                        "relative_path": "Document-Fraud-Detection/second",
                        "task_hash": HASH,
                    },
                ],
                "invalid_reasons": [],
            },
            {
                "family": "OCR-Data-Extraction",
                "status": "ready",
                "ranking_hash": HASH,
                "ranked_task_ids": ["ocr-first"],
                "tasks": [
                    {
                        "task_id": "ocr-first",
                        "order": 1,
                        "relative_path": "OCR-Data-Extraction/ocr-first",
                        "task_hash": HASH,
                    }
                ],
                "invalid_reasons": [],
            },
        ],
        "provider_calls": 0,
    }


def test_input_manifest_accepts_exact_batches_and_order() -> None:
    manifest = SkillFlowInputManifest.model_validate(_payload())

    assert manifest.replicates == ["r1", "r2", "r3"]
    assert manifest.batch_a == ["Document-Fraud-Detection"]
    assert manifest.batch_b == ["OCR-Data-Extraction"]
    assert [task.order for task in manifest.families[0].tasks] == [1, 2]

    with pytest.raises(ValidationError):
        manifest.replicates = ["r1"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.update(replicates=["r1", "r1", "r3"]),
        lambda row: row.update(batch_b=["Document-Fraud-Detection"]),
        lambda row: row["families"][0]["tasks"][1].update(order=3),
        lambda row: row["families"][0]["tasks"][1].update(task_id="first"),
        lambda row: row["families"][0]["tasks"][0].update(
            relative_path="../outside"
        ),
        lambda row: row["families"][0].update(
            status="invalid", invalid_reasons=[]
        ),
    ],
)
def test_input_manifest_rejects_ambiguous_identity(mutate) -> None:
    payload = deepcopy(_payload())
    mutate(payload)

    with pytest.raises(ValidationError):
        SkillFlowInputManifest.model_validate(payload)


def test_input_manifest_retains_invalid_candidate_in_denominator() -> None:
    payload = _payload()
    family = payload["families"][0]
    family["status"] = "invalid"
    family["ranked_task_ids"] = ["first", "second", "missing"]
    family["invalid_reasons"] = ["ranking_missing_task:missing"]

    manifest = SkillFlowInputManifest.model_validate(payload)

    assert manifest.families[0].status == "invalid"
    assert manifest.families[0].invalid_reasons == ["ranking_missing_task:missing"]
