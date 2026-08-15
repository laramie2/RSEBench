import json
from pathlib import Path

from rsebench.evidence import canonical_hash
from rsebench.selection import ExposureLevel, ExposureSource, build_exposure_registry


def test_score_observed_dominates_manifest_only(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    result = tmp_path / "result.json"
    manifest.write_text(
        json.dumps(
            {"benchmark": "webshop", "train": [{"task_id": "goal_1"}]}
        ),
        encoding="utf-8",
    )
    result.write_text(
        json.dumps(
            {"benchmark": "webshop", "per_task_scores": {"goal_1": 1.0}}
        ),
        encoding="utf-8",
    )

    registry = build_exposure_registry(
        [
            ExposureSource(
                label="manifest",
                root=manifest,
                level=ExposureLevel.manifest_only,
            ),
            ExposureSource(
                label="result",
                root=result,
                level=ExposureLevel.score_observed,
            ),
        ]
    )

    assert registry.records[0].level == ExposureLevel.score_observed
    assert registry.records[0].roles == ["per_task_scores", "train"]
    assert registry.records[0].sources == ["manifest", "result"]


def test_registry_serialization_never_contains_source_absolute_path(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "machine-specific-root"
    source_root.mkdir()
    (source_root / "manifest.json").write_text(
        json.dumps({"benchmark": "officeqa_full", "test": ["UID0042"]}),
        encoding="utf-8",
    )

    registry = build_exposure_registry(
        [
            ExposureSource(
                label="portable-label",
                root=source_root.resolve(),
                level=ExposureLevel.manifest_only,
            )
        ]
    )

    serialized = registry.model_dump_json()
    assert str(source_root.resolve()) not in serialized
    assert "portable-label" in serialized


def test_scanner_reads_only_declared_id_bearing_fields(tmp_path: Path) -> None:
    source = tmp_path / "records.json"
    source.write_text(
        json.dumps(
            {
                "benchmark": "webshop",
                "train": ["goal_1", {"task_id": "goal_2"}],
                "per_task_scores": {"goal_3": 0.5},
                "tasks": [{"level": "task", "task_id": "goal_4"}],
                "native": [{"goal_idx": 5}],
                "instances": [{"task_id": "skill-family-1"}],
                "message": "goal_not_an_id",
                "metadata": {
                    "task_id": "goal_nested_arbitrary",
                    "note": "goal_also_not_an_id",
                },
            }
        ),
        encoding="utf-8",
    )

    registry = build_exposure_registry(
        [
            ExposureSource(
                label="records",
                root=source,
                level=ExposureLevel.executed,
            )
        ]
    )

    assert [(record.benchmark, record.task_id) for record in registry.records] == [
        ("webshop", "goal_1"),
        ("webshop", "goal_2"),
        ("webshop", "goal_3"),
        ("webshop", "goal_4"),
        ("webshop", "goal_5"),
        ("webshop", "skill-family-1"),
    ]


def test_registry_order_and_hash_are_deterministic_for_directory_input(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "z.json").write_text(
        json.dumps({"benchmark": "webshop", "test": ["goal_2"]}),
        encoding="utf-8",
    )
    (source_root / "a.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"benchmark": "officeqa_full", "test": ["UID0002"]}),
                json.dumps({"benchmark": "webshop", "test": ["goal_1"]}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    source = ExposureSource(
        label="history",
        root=source_root,
        level=ExposureLevel.manifest_only,
    )

    first = build_exposure_registry([source])
    second = build_exposure_registry([source])

    assert first == second
    assert [(row.benchmark, row.task_id) for row in first.records] == [
        ("officeqa_full", "UID0002"),
        ("webshop", "goal_1"),
        ("webshop", "goal_2"),
    ]
    assert first.registry_hash == canonical_hash(
        [record.model_dump(mode="json") for record in first.records]
    )


def test_scanner_recognizes_skilllearn_instance_id_records(tmp_path: Path) -> None:
    source = tmp_path / "skilllearn_manifest.json"
    source.write_text(
        json.dumps(
            {
                "outputs": {
                    "offer-letter-generator": {
                        "instance_ids": [
                            "offer-letter-generator-1",
                            "offer-letter-generator-2",
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    registry = build_exposure_registry(
        [
            ExposureSource(
                label="skilllearn-index",
                root=source,
                level=ExposureLevel.manifest_only,
            )
        ]
    )

    assert [(record.benchmark, record.task_id) for record in registry.records] == [
        ("skilllearnbench", "offer-letter-generator-1"),
        ("skilllearnbench", "offer-letter-generator-2"),
    ]
    assert registry.records[0].roles == ["skilllearn_instance"]


def test_experiment_bounds_and_source_partition_are_merged(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    result = tmp_path / "result.json"
    manifest.write_text(
        json.dumps({"benchmark": "webshop", "validation": ["goal_1"]}),
        encoding="utf-8",
    )
    result.write_text(
        json.dumps({"benchmark": "webshop", "per_task_scores": {"goal_1": 1}}),
        encoding="utf-8",
    )

    registry = build_exposure_registry(
        [
            ExposureSource(
                label="first",
                root=manifest,
                level=ExposureLevel.manifest_only,
                experiment_id="experiment-1",
            ),
            ExposureSource(
                label="last",
                root=result,
                level=ExposureLevel.score_observed,
                experiment_id="experiment-2",
            ),
        ]
    )

    assert registry.records[0].source_partition == "validation"
    assert registry.records[0].first_experiment_id == "experiment-1"
    assert registry.records[0].last_experiment_id == "experiment-2"
