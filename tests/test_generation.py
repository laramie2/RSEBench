import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from openpyxl import Workbook

import rsebench.generation as generation


@pytest.fixture
def isolated_generation_root(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    data = tmp_path / "data"
    methods = tmp_path / "methods"
    outputs = tmp_path / "outputs"
    (project / "configs").mkdir(parents=True)
    (project / "configs" / "model.yaml").write_text(
        "provider: deepseek\n"
        "base_url: https://api.deepseek.com\n"
        "model: deepseek-v4-flash\n"
        "api_key_env: DEEPSEEK_API_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(generation, "PROJECT_ROOT", project)
    monkeypatch.setenv("RSEBENCH_DATA_ROOT", str(data))
    monkeypatch.setenv("RSEBENCH_METHODS_ROOT", str(methods))
    monkeypatch.setenv("RSEBENCH_OUTPUT_ROOT", str(outputs))
    return project, data, methods, outputs


def _profile(project: Path, name: str, payload: dict) -> Path:
    path = project / f"{name}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_formal_officeqa_is_explicitly_blocked_when_gated_data_is_missing(
    isolated_generation_root,
):
    project, _, _, _ = isolated_generation_root
    profile = _profile(
        project,
        "officeqa",
        {
            "benchmark": "officeqa_full",
            "model_config": "configs/model.yaml",
            "dataset_path": "missing/questions.json",
            "corpus_path": "missing/corpus",
            "operators": ["semantic_decoy_document"],
            "seed": 7,
        },
    )

    summary = generation.generate_from_profile(profile, limit=1, offline=True)

    assert summary.status == "blocked"
    assert summary.counts == {"blocked_access": 1}
    assert Path(summary.run_dir, "summary.json").is_file()


def test_formal_officeqa_generates_from_materialized_csv_and_nested_corpus(
    isolated_generation_root,
):
    project, data, _, _ = isolated_generation_root
    materialized = data / "materialized" / "officeqa_full"
    corpus = materialized / "corpus" / "treasury_bulletins_transformed"
    corpus.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "uid": "UID1",
                "question": "What was the veterans budget?",
                "answer": "[507, 508]",
                "source_files": "gold.txt\r\ngold-2.txt",
            }
        ]
    ).to_csv(materialized / "officeqa_full.csv", index=False)
    (corpus / "gold.txt").write_text("official source", encoding="utf-8")
    (corpus / "gold-2.txt").write_text("second official source", encoding="utf-8")
    (corpus / "decoy-a.txt").write_text(
        "veterans budget estimates for a later period", encoding="utf-8"
    )
    (corpus / "decoy-b.txt").write_text(
        "veterans budget discussion for an earlier period", encoding="utf-8"
    )
    profile = _profile(
        project,
        "officeqa-formal",
        {
            "benchmark": "officeqa_full",
            "model_config": "configs/model.yaml",
            "dataset_path": "materialized/officeqa_full/officeqa_full.csv",
            "corpus_path": "materialized/officeqa_full/corpus",
            "operators": [
                "semantic_decoy_document",
                "gold_rank_displacement",
                "failed_attempt",
            ],
            "gold_ranks": [2, 3, 4],
            "seed": 17,
            "smoke_severity": "L2",
        },
    )

    summary = generation.generate_from_profile(profile, limit=1, offline=True)

    assert summary.status == "generation_validated"
    assert summary.counts == {"accepted": 3}
    assert summary.records[0].manifest.benchmark == "officeqa_full"
    assert summary.records[1].validation.checks["gold_rank"] == 3
    assert summary.records[1].validation.checks["gold_document_count"] == 2
    assert all(
        Path(record.artifact_path).is_file()
        for record in summary.records[:2]
    )


def test_docvqa_profile_keeps_prompt_noise_and_marks_image_noise_not_applicable(
    isolated_generation_root,
):
    project, data, _, _ = isolated_generation_root
    dataset = data / "docvqa.parquet"
    data.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "questionId": 17,
                "question": "What is the total?",
                "answers": ["42"],
                "docId": "doc-1",
            }
        ]
    ).to_parquet(dataset)
    profile = _profile(
        project,
        "docvqa",
        {
            "benchmark": "docvqa_10pct",
            "model_config": "configs/model.yaml",
            "dataset_path": "docvqa.parquet",
            "operators": ["redundant_context", "margin_clutter"],
            "seed": 11,
            "smoke_severity": "L2",
        },
    )

    summary = generation.generate_from_profile(profile, limit=1, offline=True)

    assert summary.counts == {"accepted": 1, "not_applicable": 1}
    assert summary.records[1].validation is not None
    assert not summary.records[1].validation.applicable


def test_math_profile_separates_rule_noise_from_offline_model_block(
    isolated_generation_root,
):
    project, data, _, _ = isolated_generation_root
    dataset = data / "dapo.parquet"
    data.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "normalized_problem_hash": "a" * 64,
                "prompt": [{"role": "user", "content": "Compute 2+2."}],
                "reward_model": {"ground_truth": "4"},
            }
        ]
    ).to_parquet(dataset)
    profile = _profile(
        project,
        "math",
        {
            "benchmark": "dapo_fixed_1000",
            "model_config": "configs/model.yaml",
            "dataset_path": "dapo.parquet",
            "operators": ["failed_attempt", "flawed_partial_solution"],
            "seed": 13,
            "smoke_severity": "L2",
        },
    )

    summary = generation.generate_from_profile(profile, limit=1, offline=True)

    assert summary.status == "partial"
    assert summary.counts == {"accepted": 1, "blocked_model": 1}


def test_math_generation_rejection_is_recorded_without_aborting_batch(
    tmp_path: Path, monkeypatch
):
    dataset = tmp_path / "dapo.parquet"
    pd.DataFrame(
        [
            {
                "normalized_problem_hash": "b" * 64,
                "prompt": [{"role": "user", "content": "Compute 3+3."}],
                "reward_model": {"ground_truth": "6"},
            }
        ]
    ).to_parquet(dataset)
    from rsebench.domains.math import CandidateGenerationError

    def reject_candidate(**kwargs):
        raise CandidateGenerationError("critic rejected all attempts")

    monkeypatch.setattr(generation, "generate_flawed_solution", reject_candidate)
    records = generation._math_records(
        {
            "dataset_path": "dapo.parquet",
            "operators": ["flawed_partial_solution"],
            "seed": 23,
        },
        tmp_path,
        limit=1,
        severity="L2",
        offline=False,
        client=object(),
    )

    assert len(records) == 1
    assert records[0].status == "rejected_generation"
    assert "critic rejected" in records[0].detail


def test_spreadsheet_generation_materializes_and_validates_both_artifact_operators(
    tmp_path: Path,
):
    dataset_root = tmp_path / "spreadsheet"
    task_dir = dataset_root / "task-1"
    task_dir.mkdir(parents=True)
    clean = task_dir / "task-1_init.xlsx"
    gold = task_dir / "task-1_golden.xlsx"
    workbook = Workbook()
    workbook.active.title = "Data"
    workbook.active["A1"] = 2
    answer = workbook.create_sheet("Answer")
    answer["A1"] = "=Data!A1"
    workbook.save(clean)
    answer["A1"] = 2
    workbook.save(gold)
    (dataset_root / "dataset.json").write_text(
        json.dumps(
            [
                {
                    "id": "task-1",
                    "spreadsheet_path": "task-1",
                    "instruction": "Fill Answer!A1.",
                    "answer_sheet": "Answer",
                    "answer_position": "A1",
                }
            ]
        ),
        encoding="utf-8",
    )
    config = {
        "dataset_path": "spreadsheet",
        "operators": ["stale_backup_sheet", "semantic_decoy_sheet"],
        "seed": 5,
    }

    records = generation._spreadsheet_records(
        config, tmp_path, tmp_path / "run", limit=1, severity="L2"
    )

    assert [record.status for record in records] == ["accepted", "accepted"]
    assert all(Path(record.artifact_path).is_file() for record in records)


def test_officeqa_demo_materializes_semantic_and_rank_decoys(tmp_path: Path):
    methods = tmp_path / "methods"
    corpus = methods / "demo" / "corpus"
    corpus.mkdir(parents=True)
    (methods / "demo" / "questions.csv").write_text(
        "uid,question,answer,source_files\n"
        "UID1,What was the veterans budget?,507,gold.txt\n",
        encoding="utf-8",
    )
    (corpus / "gold.txt").write_text("official source", encoding="utf-8")
    (corpus / "decoy-a.txt").write_text(
        "veterans budget estimates for a later period", encoding="utf-8"
    )
    (corpus / "decoy-b.txt").write_text(
        "veterans budget discussion for an earlier period", encoding="utf-8"
    )
    config = {
        "dataset_path": "demo/questions.csv",
        "corpus_path": "demo/corpus",
        "operators": ["semantic_decoy_document", "gold_rank_displacement"],
        "gold_ranks": {"L2": 3},
        "seed": 19,
    }

    records = generation._officeqa_demo_records(
        config, methods, tmp_path / "run", limit=1, severity="L2"
    )

    assert [record.status for record in records] == ["accepted", "accepted"]
    assert all(Path(record.artifact_path).is_file() for record in records)


def test_unknown_generation_benchmark_is_rejected(isolated_generation_root):
    project, _, _, _ = isolated_generation_root
    profile = _profile(
        project,
        "unknown",
        {
            "benchmark": "unknown",
            "model_config": "configs/model.yaml",
            "operators": [],
            "seed": 1,
        },
    )
    with pytest.raises(ValueError, match="unsupported generation benchmark"):
        generation.generate_from_profile(profile, offline=True)


def test_generation_status_treats_typed_rejections_as_partial():
    assert generation._generation_status(
        {"accepted": 5, "rejected_generation": 5}
    ) == "partial"
