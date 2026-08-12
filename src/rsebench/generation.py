"""Offline/model-backed domain noise generation with immutable audit records."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from rsebench.contracts import NoiseManifest, Severity, TaskManifest, ValidationReport
from rsebench.domains.math import generate_flawed_solution, validate_flawed_solution
from rsebench.domains.officeqa import (
    OfficeQATask,
    build_corpus_index,
    build_decoy_index,
    build_question_vocabulary,
    build_rank_fixture,
    select_decoy_documents,
    validate_officeqa_noise,
)
from rsebench.domains.spreadsheet import (
    SpreadsheetTask,
    inject_backup_sheet,
    inject_semantic_decoy_sheet,
    validate_spreadsheet_noise,
)
from rsebench.hashing import sha256_file
from rsebench.noise.instruction import FailedAttempt, RedundantContext, RelatedDistractor
from rsebench.pilot import create_run_directory
from rsebench.providers.deepseek import CredentialsMissingError, DeepSeekClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GenerationRecord(BaseModel):
    task_id: str
    operator: str
    severity: str
    status: str
    validation: ValidationReport | None = None
    manifest: NoiseManifest | None = None
    artifact_path: str | None = None
    detail: str | None = None


class GenerationSummary(BaseModel):
    run_id: str
    run_dir: str
    profile: str
    benchmark: str
    model: str = "deepseek-v4-flash"
    offline: bool
    status: str
    counts: dict[str, int] = Field(default_factory=dict)
    records: list[GenerationRecord] = Field(default_factory=list)


def _run_id(profile: Path, offline: bool) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(
        profile.read_bytes() + (b":offline" if offline else b":model")
    ).hexdigest()[:10]
    return f"{stamp}-{digest}"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prompt_text(value: Any) -> str:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("content", ""))
    return str(value)


def _instruction_operator(name: str):
    return {
        "failed_attempt": FailedAttempt,
        "related_distractor": RelatedDistractor,
        "redundant_context": RedundantContext,
    }[name]


def _spreadsheet_records(
    config: dict,
    data_root: Path,
    run_dir: Path,
    limit: int,
    severity: str,
) -> list[GenerationRecord]:
    dataset_root = data_root / config["dataset_path"]
    rows = json.loads((dataset_root / "dataset.json").read_text(encoding="utf-8"))
    selected = sorted(rows, key=lambda row: _hash_text(str(row["id"])))[:limit]
    records: list[GenerationRecord] = []
    artifacts = run_dir / "artifacts"
    for row in selected:
        task_dir = dataset_root / row["spreadsheet_path"]
        initial = next(iter(sorted(task_dir.glob("*_init.xlsx"))), None)
        gold = next(iter(sorted(task_dir.glob("*_golden.xlsx"))), None)
        initial = initial or (task_dir / "initial.xlsx")
        gold = gold or (task_dir / "golden.xlsx")
        task = SpreadsheetTask.from_paths(
            task_id=str(row["id"]),
            workbook_path=initial,
            gold_workbook_path=gold,
            prompt=str(row["instruction"]),
            answer_sheet=str(row.get("answer_sheet", "")),
            answer_range=str(row.get("answer_position", "")),
        )
        generic = TaskManifest(
            task_id=task.task_id,
            benchmark="spreadsheetbench_verified",
            domain="spreadsheet",
            prompt=task.prompt,
            verifier="spreadsheetbench_cell_range_v1",
            source_hash=task.clean_hash,
            artifact_path=str(task.workbook_path),
        )
        for operator in config["operators"]:
            if operator in {"failed_attempt", "related_distractor", "redundant_context"}:
                result = _instruction_operator(operator)().generate(
                    generic, severity=severity, seed=int(config["seed"])
                )
                records.append(
                    GenerationRecord(
                        task_id=task.task_id,
                        operator=operator,
                        severity=severity,
                        status="accepted" if result.validation.accepted else "rejected",
                        validation=result.validation,
                        manifest=result.manifest,
                    )
                )
                continue
            function = {
                "stale_backup_sheet": inject_backup_sheet,
                "semantic_decoy_sheet": inject_semantic_decoy_sheet,
            }.get(operator)
            if function is None:
                continue
            output = artifacts / f"{task.task_id}-{operator}-{severity}.xlsx"
            result = function(
                task, output, severity=severity, seed=int(config["seed"])
            )
            validation = validate_spreadsheet_noise(task, result)
            mechanism = "M4" if operator == "stale_backup_sheet" else "M1"
            manifest = NoiseManifest(
                noise_id=f"{task.task_id}-C2-{mechanism}-{operator}-{severity}",
                task_id=task.task_id,
                channel="C2",
                mechanism=mechanism,
                operator=operator,
                domain="spreadsheet",
                benchmark="spreadsheetbench_verified",
                severity=Severity(level=severity, budget={"L1": 1, "L2": 2, "L3": 3}[severity]),
                seed=int(config["seed"]),
                clean_hash=result.clean_hash,
                noisy_hash=result.noisy_hash,
            )
            records.append(
                GenerationRecord(
                    task_id=task.task_id,
                    operator=operator,
                    severity=severity,
                    status="accepted" if validation.accepted else "rejected",
                    validation=validation,
                    manifest=manifest,
                    artifact_path=str(output),
                )
            )
    return records


def _docvqa_records(
    config: dict, data_root: Path, limit: int, severity: str
) -> list[GenerationRecord]:
    dataset = data_root / config["dataset_path"]
    frame = pd.read_parquet(
        dataset, columns=["questionId", "question", "answers", "docId"]
    )
    frame["sort_key"] = frame["questionId"].astype(str).map(_hash_text)
    records: list[GenerationRecord] = []
    for row in frame.sort_values("sort_key").head(limit).itertuples(index=False):
        answers = [str(answer) for answer in row.answers]
        source_hash = _hash_text(
            json.dumps(
                [str(row.questionId), str(row.question), answers], ensure_ascii=False
            )
        )
        task = TaskManifest(
            task_id=str(row.questionId),
            benchmark="docvqa_10pct",
            domain="document",
            prompt=str(row.question),
            gold_answers=answers,
            source_hash=source_hash,
            metadata={"doc_id": str(row.docId)},
        )
        for operator in config["operators"]:
            if operator in {"failed_attempt", "related_distractor", "redundant_context"}:
                result = _instruction_operator(operator)().generate(
                    task, severity=severity, seed=int(config["seed"])
                )
                records.append(
                    GenerationRecord(
                        task_id=task.task_id,
                        operator=operator,
                        severity=severity,
                        status="accepted" if result.validation.accepted else "rejected",
                        validation=result.validation,
                        manifest=result.manifest,
                    )
                )
            elif operator == "margin_clutter":
                validation = ValidationReport(
                    structural_valid=True,
                    label_invariant=True,
                    solvable=True,
                    answer_leak_free=True,
                    accepted=False,
                    applicable=False,
                    messages=["answer_region_unavailable_in_released_subset"],
                )
                records.append(
                    GenerationRecord(
                        task_id=task.task_id,
                        operator=operator,
                        severity=severity,
                        status="not_applicable",
                        validation=validation,
                        detail="requires OCR boxes or supplied answer localization",
                    )
                )
    return records


def _math_records(
    config: dict,
    data_root: Path,
    limit: int,
    severity: str,
    offline: bool,
    client: DeepSeekClient,
) -> list[GenerationRecord]:
    dataset = data_root / config["dataset_path"]
    frame = pd.read_parquet(dataset)
    frame = frame.sort_values("normalized_problem_hash").head(limit)
    records: list[GenerationRecord] = []
    for row in frame.itertuples(index=False):
        problem = _prompt_text(row.prompt)
        reward = row.reward_model if isinstance(row.reward_model, dict) else {}
        gold = str(reward.get("ground_truth", ""))
        task = TaskManifest(
            task_id=str(row.normalized_problem_hash),
            benchmark="dapo_fixed_1000",
            domain="math",
            prompt=problem,
            gold_answers=[gold],
            source_hash=str(row.normalized_problem_hash),
        )
        for operator in config["operators"]:
            if operator == "failed_attempt":
                result = FailedAttempt().generate(
                    task, severity=severity, seed=int(config["seed"])
                )
                records.append(
                    GenerationRecord(
                        task_id=task.task_id,
                        operator=operator,
                        severity=severity,
                        status="accepted" if result.validation.accepted else "rejected",
                        validation=result.validation,
                        manifest=result.manifest,
                    )
                )
            elif operator == "flawed_partial_solution":
                if offline:
                    records.append(
                        GenerationRecord(
                            task_id=task.task_id,
                            operator=operator,
                            severity=severity,
                            status="blocked_model",
                            detail="model-backed operator disabled by --offline",
                        )
                    )
                    continue
                try:
                    candidate = generate_flawed_solution(
                        problem=problem,
                        gold_answer=gold,
                        task_hash=task.source_hash,
                        client=client,
                        severity=severity,
                        seed=int(config["seed"]),
                        max_attempts=int(config.get("generation", {}).get("max_attempts", 3)),
                    )
                    validation = validate_flawed_solution(candidate, gold)
                    records.append(
                        GenerationRecord(
                            task_id=task.task_id,
                            operator=operator,
                            severity=severity,
                            status="accepted" if validation.accepted else "rejected",
                            validation=validation,
                        )
                    )
                except CredentialsMissingError as exc:
                    records.append(
                        GenerationRecord(
                            task_id=task.task_id,
                            operator=operator,
                            severity=severity,
                            status="blocked_credentials",
                            detail=str(exc),
                        )
                    )
    return records


def _officeqa_answers(value: Any) -> list[str]:
    text = str(value)
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, list) and parsed:
            return [str(item) for item in parsed]
    return [text]


def _officeqa_gold_rank(config: dict, severity: str) -> int:
    ranks = config["gold_ranks"]
    if isinstance(ranks, dict):
        return int(ranks[severity])
    return int(ranks[("L1", "L2", "L3").index(severity)])


def _resolve_officeqa_document_id(
    source_file: str, documents_by_id: dict[str, Any]
) -> str:
    if source_file in documents_by_id:
        return source_file
    matches = [
        document_id
        for document_id in documents_by_id
        if Path(document_id).name == Path(source_file).name
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one corpus match for {source_file}, found {len(matches)}"
        )
    return matches[0]


def _resolve_officeqa_document_ids(
    source_files: str, documents_by_id: dict[str, Any]
) -> list[str]:
    requested = [value.strip() for value in source_files.splitlines() if value.strip()]
    if not requested:
        raise ValueError("OfficeQA row has no source files")
    return [
        _resolve_officeqa_document_id(source_file, documents_by_id)
        for source_file in requested
    ]


def _officeqa_records(
    config: dict,
    dataset: Path,
    corpus_root: Path,
    run_dir: Path,
    limit: int,
    severity: str,
    benchmark: str,
) -> list[GenerationRecord]:
    frame = pd.read_csv(dataset).sort_values("uid").head(limit)
    documents = build_corpus_index(corpus_root)
    decoy_index = build_decoy_index(
        documents,
        vocabulary=build_question_vocabulary(frame["question"].astype(str)),
    )
    documents_by_id = {document.document_id: document for document in documents}
    records: list[GenerationRecord] = []
    fixture_root = run_dir / "retrieval_fixtures"
    fixture_root.mkdir(parents=True, exist_ok=True)
    for row in frame.itertuples(index=False):
        gold_document_ids = _resolve_officeqa_document_ids(
            str(row.source_files), documents_by_id
        )
        task = OfficeQATask(
            task_id=str(row.uid),
            question=str(row.question),
            answers=_officeqa_answers(row.answer),
            gold_document_id=gold_document_ids[0],
            source_document_ids=gold_document_ids[1:],
        )
        clean_hash = _hash_text(
            json.dumps(
                [task.task_id, task.question, task.answers, gold_document_ids],
                ensure_ascii=False,
            )
        )
        generic = TaskManifest(
            task_id=task.task_id,
            benchmark=benchmark,
            domain="document",
            prompt=task.question,
            gold_answers=task.answers,
            source_hash=clean_hash,
            metadata={"gold_document_ids": gold_document_ids},
        )
        decoys = select_decoy_documents(
            task, documents, limit=8, index=decoy_index
        )
        for operator in config["operators"]:
            if operator == "failed_attempt":
                result = FailedAttempt().generate(
                    generic, severity=severity, seed=int(config["seed"])
                )
                records.append(
                    GenerationRecord(
                        task_id=task.task_id,
                        operator=operator,
                        severity=severity,
                        status="accepted" if result.validation.accepted else "rejected",
                        validation=result.validation,
                        manifest=result.manifest,
                    )
                )
                continue
            gold_rank = (
                1
                if operator == "semantic_decoy_document"
                else _officeqa_gold_rank(config, severity)
            )
            try:
                fixture = build_rank_fixture(task, decoys=decoys, gold_rank=gold_rank)
            except ValueError as exc:
                records.append(
                    GenerationRecord(
                        task_id=task.task_id,
                        operator=operator,
                        severity=severity,
                        status="not_applicable",
                        detail=str(exc),
                    )
                )
                continue
            validation = validate_officeqa_noise(task, fixture)
            fixture_path = fixture_root / f"{task.task_id}-{operator}-{severity}.json"
            fixture_path.write_text(
                fixture.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            channel = "C2" if operator == "semantic_decoy_document" else "C3"
            mechanism = "M1" if operator == "semantic_decoy_document" else "M5"
            manifest = NoiseManifest(
                noise_id=f"{task.task_id}-{channel}-{mechanism}-{operator}-{severity}",
                task_id=task.task_id,
                channel=channel,
                mechanism=mechanism,
                operator=operator,
                domain="document",
                benchmark=benchmark,
                severity=Severity(
                    level=severity,
                    budget=(len(decoys) if gold_rank == 1 else gold_rank - 1),
                ),
                seed=int(config["seed"]),
                clean_hash=clean_hash,
                noisy_hash=fixture.fixture_hash,
            )
            records.append(
                GenerationRecord(
                    task_id=task.task_id,
                    operator=operator,
                    severity=severity,
                    status="accepted" if validation.accepted else "rejected",
                    validation=validation,
                    manifest=manifest,
                    artifact_path=str(fixture_path),
                )
            )
    return records


def _officeqa_demo_records(
    config: dict,
    methods_root: Path,
    run_dir: Path,
    limit: int,
    severity: str,
) -> list[GenerationRecord]:
    return _officeqa_records(
        config,
        methods_root / config["dataset_path"],
        methods_root / config["corpus_path"],
        run_dir,
        limit,
        severity,
        "officeqa_demo_10",
    )


def generate_from_profile(
    profile_path: Path | str,
    *,
    limit: int | None = None,
    offline: bool = False,
) -> GenerationSummary:
    load_dotenv(PROJECT_ROOT / ".env")
    profile = Path(profile_path)
    config = yaml.safe_load(profile.read_text(encoding="utf-8"))
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    methods_root = Path(
        os.environ.get("RSEBENCH_METHODS_ROOT", PROJECT_ROOT / "methods/external")
    )
    output_root = Path(
        os.environ.get("RSEBENCH_OUTPUT_ROOT", PROJECT_ROOT / "outputs")
    )
    run_id = _run_id(profile, offline)
    run_dir = create_run_directory(output_root, "generation", run_id)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    selected_limit = int(limit or config.get("pilot_limit", 10))
    severity = str(config.get("smoke_severity", "L2"))
    client = DeepSeekClient.from_yaml(PROJECT_ROOT / config["model_config"])
    benchmark = str(config["benchmark"])
    if benchmark == "spreadsheetbench_verified":
        records = _spreadsheet_records(
            config, data_root, run_dir, selected_limit, severity
        )
    elif benchmark == "docvqa_10pct":
        records = _docvqa_records(config, data_root, selected_limit, severity)
    elif benchmark == "dapo_fixed_1000":
        records = _math_records(
            config, data_root, selected_limit, severity, offline, client
        )
    elif benchmark == "officeqa_full":
        dataset = data_root / config["dataset_path"]
        corpus = data_root / config["corpus_path"]
        if not dataset.exists() or not corpus.exists():
            records = [
                GenerationRecord(
                    task_id="*",
                    operator="*",
                    severity=severity,
                    status="blocked_access",
                    detail="OfficeQA gated dataset/corpus is unavailable",
                )
            ]
        else:
            records = _officeqa_records(
                config,
                dataset,
                corpus,
                run_dir,
                selected_limit,
                severity,
                "officeqa_full",
            )
    elif benchmark == "officeqa_demo_10":
        records = _officeqa_demo_records(
            config, methods_root, run_dir, selected_limit, severity
        )
    else:
        raise ValueError(f"unsupported generation benchmark: {benchmark}")
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    blockers = sum(
        count for status, count in counts.items() if status.startswith("blocked")
    )
    rejected = counts.get("rejected", 0)
    accepted = counts.get("accepted", 0)
    status = (
        "blocked"
        if accepted == 0 and blockers
        else "partial"
        if blockers or rejected
        else "generation_validated"
    )
    summary = GenerationSummary(
        run_id=run_id,
        run_dir=str(run_dir),
        profile=str(profile),
        benchmark=benchmark,
        offline=offline,
        status=status,
        counts=counts,
        records=records,
    )
    (run_dir / "summary.json").write_text(
        summary.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return summary
