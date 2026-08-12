import hashlib

import pytest
import yaml
from openpyxl import Workbook

import rsebench.generation as generation
from rsebench.contracts import NoiseManifest, Severity, TaskManifest, ValidationReport
from rsebench.evolution.noise_generation import (
    PairGenerationError,
    PairedNoiseRecord,
    assemble_evolution_split,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _task(task_id: str, prompt: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="math",
        prompt=prompt,
        gold_answers=["42"],
        source_hash=_hash(prompt),
    )


def _record(task_id: str, accepted: bool = True) -> PairedNoiseRecord:
    clean = _task(task_id, f"clean {task_id}")
    noisy = _task(task_id, f"noisy {task_id}")
    report = ValidationReport(
        structural_valid=accepted,
        label_invariant=True,
        solvable=accepted,
        answer_leak_free=True,
        accepted=accepted,
    )
    noise = NoiseManifest(
        noise_id=f"noise-{task_id}",
        task_id=task_id,
        channel="C1",
        mechanism="M2",
        operator="flawed_partial_solution",
        domain="math",
        benchmark="fixture",
        severity=Severity(level="L2", budget=1),
        seed=1,
        clean_hash=clean.source_hash,
        noisy_hash=noisy.source_hash,
        timing="evolution",
        generator_mode="model",
    )
    return PairedNoiseRecord(
        task_id=task_id,
        operator="flawed_partial_solution",
        clean=clean,
        noisy=noisy,
        noise=noise,
        validation=report,
    )


def test_assemble_pairs_noises_only_train_and_validation():
    clean_test = _task("test", "untouched test")
    split = assemble_evolution_split(
        benchmark="fixture",
        domain="math",
        seed=9,
        source_hash=_hash("source"),
        records=[_record("train"), _record("validation")],
        train_ids=["train"],
        validation_ids=["validation"],
        clean_test=[clean_test],
    )

    assert split.train[0].noise.timing.value == "evolution"
    assert split.validation[0].noise.timing.value == "evolution"
    assert split.clean_test == [clean_test]
    assert split.clean_test[0].source_hash == _hash("untouched test")


def test_rejected_noise_prevents_manifest_materialization():
    with pytest.raises(PairGenerationError, match="hard gates"):
        assemble_evolution_split(
            benchmark="fixture",
            domain="math",
            seed=9,
            source_hash=_hash("source"),
            records=[_record("train", accepted=False)],
            train_ids=["train"],
            validation_ids=[],
            clean_test=[_task("test", "untouched")],
        )


def test_test_id_cannot_appear_in_noisy_records():
    with pytest.raises(PairGenerationError, match="clean_test"):
        assemble_evolution_split(
            benchmark="fixture",
            domain="math",
            seed=9,
            source_hash=_hash("source"),
            records=[_record("test")],
            train_ids=[],
            validation_ids=[],
            clean_test=[_task("test", "clean test")],
        )


def test_profile_pipeline_materializes_only_evolution_pairs(tmp_path, monkeypatch):
    project = tmp_path / "project"
    data = tmp_path / "data"
    outputs = tmp_path / "outputs"
    dataset = data / "spreadsheet"
    project.mkdir()
    rows = []
    for task_id in ("train", "validation", "test"):
        task_dir = dataset / task_id
        task_dir.mkdir(parents=True)
        workbook = Workbook()
        workbook.active.title = "Data"
        workbook.active["A1"] = 1
        workbook.save(task_dir / f"{task_id}_init.xlsx")
        workbook.active["A1"] = 2
        workbook.save(task_dir / f"{task_id}_golden.xlsx")
        rows.append(
            {
                "id": task_id,
                "spreadsheet_path": task_id,
                "instruction": f"Update {task_id}.",
                "answer_sheet": "Data",
                "answer_position": "A1",
            }
        )
    (dataset / "dataset.json").write_text(
        __import__("json").dumps(rows), encoding="utf-8"
    )
    split_path = data / "split.json"
    split_path.write_text(
        __import__("json").dumps(
            {
                "benchmark": "spreadsheetbench_verified",
                "seed": 7,
                "evolution": ["train"],
                "validation": ["validation"],
                "test": ["test"],
            }
        ),
        encoding="utf-8",
    )
    profile = project / "profile.yaml"
    profile.write_text(
        yaml.safe_dump(
            {
                "benchmark": "spreadsheetbench_verified",
                "domain": "spreadsheet",
                "dataset_path": "spreadsheet",
                "split_manifest": str(split_path),
                "operator": "failed_attempt",
                "generator_mode": "rule",
                "severity": "L2",
                "seed": 7,
                "sizes": {"train": 1, "validation": 1, "clean_test": 1},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(generation, "PROJECT_ROOT", project)
    monkeypatch.setenv("RSEBENCH_DATA_ROOT", str(data))
    monkeypatch.setenv("RSEBENCH_OUTPUT_ROOT", str(outputs))

    summary = generation.generate_evolution_pairs_from_profile(profile, offline=True)

    assert summary.status == "generation_validated"
    manifest = summary.pair_manifest
    assert manifest is not None
    assert [pair.task_id for pair in manifest.train] == ["train"]
    assert [pair.task_id for pair in manifest.validation] == ["validation"]
    assert [task.task_id for task in manifest.clean_test] == ["test"]
    assert "test" not in {record.task_id for record in summary.records}


def test_profile_split_path_falls_back_to_shared_data_root(tmp_path, monkeypatch):
    project = tmp_path / "worktree"
    data = tmp_path / "shared-data"
    project.mkdir()
    split = data / "splits" / "fixture" / "split_manifest.json"
    split.parent.mkdir(parents=True)
    split.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(generation, "PROJECT_ROOT", project)
    monkeypatch.setenv("RSEBENCH_DATA_ROOT", str(data))

    assert generation._resolve_split_path(
        "data/splits/fixture/split_manifest.json", data
    ) == split


def test_livemath_profile_builds_native_metadata_and_clean_test(tmp_path, monkeypatch):
    import json

    project = tmp_path / "project"
    data = tmp_path / "data"
    outputs = tmp_path / "outputs"
    dataset = data / "livemath" / "202601"
    dataset.mkdir(parents=True)
    project.mkdir()
    rows = []
    for number in (1, 2, 3):
        rows.append(
            {
                "month": "202601",
                "no": number,
                "paper_link": f"https://example.test/{number}",
                "theorem_type": ["Inequality"],
                "mcq": {
                    "question": f"Question {number}",
                    "choices": [
                        {"label": "A", "text": "wrong"},
                        {"label": "B", "text": f"correct answer {number}"},
                    ],
                    "correct_choice": {
                        "label": "B",
                        "text": f"correct answer {number}",
                    },
                },
            }
        )
    (dataset / "qa_202601_final.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )
    split_path = data / "split.json"
    split_path.write_text(
        json.dumps(
                {
                    "benchmark": "livemathematicianbench",
                    "seed": 7,
                    "evolution": ["202601:1"],
                    "pilot_evolve": ["202601:1", "202601:2"],
                    "pilot_eval": ["202601:3"],
                    "validation": ["202601:2"],
                "test": ["202601:3"],
            }
        ),
        encoding="utf-8",
    )
    profile = project / "profile.yaml"
    profile.write_text(
        yaml.safe_dump(
            {
                "benchmark": "livemathematicianbench",
                "domain": "math",
                "dataset_path": "livemath",
                "split_manifest": str(split_path),
                "operator": "failed_attempt",
                "generator_mode": "rule",
                "severity": "L2",
                "seed": 7,
                "sizes": {"train": 1, "validation": 1, "clean_test": 1},
                "partitions": {
                    "train": "pilot_evolve",
                    "validation": "pilot_evolve",
                    "clean_test": "pilot_eval",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(generation, "PROJECT_ROOT", project)
    monkeypatch.setenv("RSEBENCH_DATA_ROOT", str(data))
    monkeypatch.setenv("RSEBENCH_OUTPUT_ROOT", str(outputs))

    summary = generation.generate_evolution_pairs_from_profile(profile, offline=True)

    assert summary.status == "generation_validated"
    assert summary.pair_manifest is not None
    task = summary.pair_manifest.train[0].clean
    assert task.gold_answers == ["correct answer 1"]
    assert task.metadata["correct_choice"]["label"] == "B"
    assert summary.pair_manifest.clean_test[0].prompt == "Question 3"
