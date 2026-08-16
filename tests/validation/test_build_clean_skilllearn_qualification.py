import json
from pathlib import Path

from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from scripts import build_clean_skilllearn_qualification as builder


def test_build_skilllearn_clean_expansion_freezes_five_exact_families(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "skilllearn_clean_expansion_v1"

    outputs = builder.build_skilllearn_clean_expansion(output_root=output_root)

    expected = [
        "offer-letter-generator",
        "court-form-filling",
        "earthquake-plate-calculation",
        "dbscan-parameter-tuning",
        "travel-planning",
    ]
    assert list(outputs) == expected
    manifests = [
        CleanEvolutionSplitManifest.model_validate_json(path.read_text())
        for path in outputs.values()
    ]
    assert sum(len(split.train) for split in manifests) == 10
    assert sum(len(split.validation) for split in manifests) == 5
    assert sum(len(split.clean_test) for split in manifests) == 13
    assert all(
        task.task_id.startswith(f"{family}-")
        for family, split in zip(expected, manifests, strict=True)
        for task in [*split.train, *split.validation, *split.clean_test]
    )
    assert all(
        str(task.artifact_path).startswith("rsebench-methods://")
        for split in manifests
        for task in [*split.train, *split.validation, *split.clean_test]
    )
    index = json.loads((output_root / "skilllearn_manifest.json").read_text())
    assert index["families"] == expected
    assert index["method_seeds"] == [20260813, 20260814, 20260815]
    assert index["total_task_counts"] == {
        "train": 10,
        "validation": 5,
        "clean_test": 13,
    }
