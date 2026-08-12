import json
from pathlib import Path

import pytest

from rsebench.contracts import NoiseManifest, Severity, TaskManifest, ValidationReport
from rsebench.hashing import sha256_file, sha256_tree


def test_noise_manifest_round_trip():
    row = NoiseManifest(
        noise_id="dapo-C1-M2-flawed-solution-L2-s42",
        channel="C1",
        mechanism="M2",
        operator="flawed_partial_solution",
        domain="math",
        benchmark="dapo_fixed_1000",
        severity=Severity(level="L2", budget=1, semantic_similarity=0.8),
        seed=42,
        clean_hash="a" * 64,
    )
    assert NoiseManifest.model_validate_json(row.model_dump_json()) == row


def test_validated_noise_requires_all_hard_gates():
    with pytest.raises(ValueError, match="hard gates"):
        ValidationReport(
            structural_valid=True,
            label_invariant=False,
            solvable=True,
            answer_leak_free=True,
            accepted=True,
        )


def test_task_manifest_requires_stable_identity_and_gold():
    task = TaskManifest(
        task_id="sheet-001",
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        prompt="Update the total.",
        gold_answers=["42"],
        source_hash="b" * 64,
    )
    assert task.task_id == "sheet-001"
    assert task.gold_answers == ["42"]


def test_hashes_are_stable_and_tree_hash_is_path_sensitive(tmp_path: Path):
    first = tmp_path / "a.txt"
    first.write_text("same", encoding="utf-8")
    digest = sha256_file(first)
    assert len(digest) == 64
    tree_a = sha256_tree(tmp_path)
    first.rename(tmp_path / "b.txt")
    assert sha256_tree(tmp_path) != tree_a


def test_exported_schemas_are_valid_json():
    root = Path(__file__).parents[1]
    for name in ("task-manifest.schema.json", "noise-manifest.schema.json"):
        payload = json.loads((root / "benchmark" / "schemas" / name).read_text())
        assert payload["type"] == "object"
