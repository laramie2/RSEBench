"""Offline/model-backed domain noise generation with immutable audit records."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from rsebench.contracts import (
    GeneratorMode,
    NoiseManifest,
    Severity,
    TaskManifest,
    ValidationReport,
)
from rsebench.domains.math import (
    CandidateGenerationError,
    generate_flawed_solution,
    validate_flawed_solution,
    wrap_failed_attempt,
)
from rsebench.evolution.contracts import EvolutionSplitManifest
from rsebench.evolution.noise_generation import (
    PairGenerationError,
    PairedNoiseRecord,
    assemble_evolution_split,
)
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
from rsebench.domains.searchqa import (
    TEMPLATE_VERSION as SEARCHQA_EVIDENCE_TEMPLATE_VERSION,
    generate_semantic_decoy_evidence,
    inject_semantic_decoy_evidence,
)
from rsebench.hashing import sha256_file
from rsebench.noise.instruction import FailedAttempt, RedundantContext, RelatedDistractor
from rsebench.pilot import create_run_directory
from rsebench.providers.deepseek import CredentialsMissingError, DeepSeekClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OFFICEQA_DOCUMENT_CACHE: dict[Path, list[Any]] = {}


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


class EvolutionGenerationSummary(BaseModel):
    run_id: str
    run_dir: str
    profile: str
    operator: str
    model: str = "deepseek-v4-flash"
    offline: bool
    status: str
    records: list[PairedNoiseRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    gate_rejections: list[str] = Field(default_factory=list)
    pair_manifest: EvolutionSplitManifest | None = None
    pair_manifest_path: str | None = None
    selection_audit: "EvolutionSelectionAudit | None" = None


class EvolutionSelectionAudit(BaseModel):
    """Label-free selection decisions recorded before any evaluation."""

    requested_sizes: dict[str, int]
    candidate_pool_sizes: dict[str, int]
    candidate_budget_sizes: dict[str, int]
    candidate_ids: dict[str, list[str]]
    selected_ids: dict[str, list[str]]
    test_ids: list[str]
    excluded_ids: list[str]


def _collect_gate_valid_records(
    candidate_ids: list[str],
    *,
    target_size: int,
    generate: Callable[[str], PairedNoiseRecord],
) -> tuple[list[PairedNoiseRecord], list[PairedNoiseRecord], list[str]]:
    """Backfill rejected candidates using only hard-gate outcomes, never scores."""
    selected: list[PairedNoiseRecord] = []
    attempted: list[PairedNoiseRecord] = []
    rejections: list[str] = []
    for task_id in candidate_ids:
        if len(selected) >= target_size:
            break
        try:
            record = generate(task_id)
        except Exception as exc:
            rejections.append(f"{task_id}: {type(exc).__name__}: {exc}")
            continue
        attempted.append(record)
        if record.validation.accepted:
            selected.append(record)
        else:
            rejections.append(f"{task_id}: noise failed hard gates")
    return selected, attempted, rejections


def _cached_officeqa_documents(corpus_root: Path) -> list[Any]:
    key = corpus_root.resolve()
    if key not in _OFFICEQA_DOCUMENT_CACHE:
        _OFFICEQA_DOCUMENT_CACHE[key] = build_corpus_index(key)
    return _OFFICEQA_DOCUMENT_CACHE[key]


def _generation_status(counts: dict[str, int]) -> str:
    blockers = sum(
        count for status, count in counts.items() if status.startswith("blocked")
    )
    rejected = sum(
        count for status, count in counts.items() if status.startswith("rejected")
    )
    accepted = counts.get("accepted", 0)
    if accepted == 0 and blockers:
        return "blocked"
    if accepted == 0 and rejected:
        return "rejected"
    if blockers or rejected:
        return "partial"
    if accepted == 0 and counts.get("not_applicable", 0):
        return "not_applicable"
    return "generation_validated"


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
                except CandidateGenerationError as exc:
                    records.append(
                        GenerationRecord(
                            task_id=task.task_id,
                            operator=operator,
                            severity=severity,
                            status="rejected_generation",
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
    status = _generation_status(counts)
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


def _load_evolution_tasks(
    config: dict[str, Any], data_root: Path, task_ids: list[str]
) -> list[TaskManifest]:
    benchmark = str(config["benchmark"])
    requested = set(task_ids)
    tasks: dict[str, TaskManifest] = {}
    if benchmark == "spreadsheetbench_verified":
        dataset_root = data_root / config["dataset_path"]
        rows = json.loads((dataset_root / "dataset.json").read_text(encoding="utf-8"))
        for row in rows:
            task_id = str(row["id"])
            if task_id not in requested:
                continue
            task_dir = dataset_root / row["spreadsheet_path"]
            initial = next(iter(sorted(task_dir.glob("*_init.xlsx"))), None)
            gold = next(iter(sorted(task_dir.glob("*_golden.xlsx"))), None)
            initial = initial or (task_dir / "initial.xlsx")
            gold = gold or (task_dir / "golden.xlsx")
            native = SpreadsheetTask.from_paths(
                task_id=task_id,
                workbook_path=initial,
                gold_workbook_path=gold,
                prompt=str(row["instruction"]),
                answer_sheet=str(row.get("answer_sheet", "")),
                answer_range=str(row.get("answer_position", "")),
            )
            tasks[task_id] = TaskManifest(
                task_id=task_id,
                benchmark=benchmark,
                domain="spreadsheet",
                prompt=native.prompt,
                verifier="spreadsheetbench_cell_range_v1",
                source_hash=native.clean_hash,
                artifact_path=str(native.workbook_path),
                metadata={
                    "gold_workbook_path": str(native.gold_workbook_path),
                    "answer_sheet": native.answer_sheet,
                    "answer_range": native.answer_range,
                },
            )
    elif benchmark == "officeqa_full":
        dataset = data_root / config["dataset_path"]
        corpus_root = data_root / config["corpus_path"]
        frame = pd.read_csv(dataset)
        documents = _cached_officeqa_documents(corpus_root)
        documents_by_id = {document.document_id: document for document in documents}
        for row in frame.itertuples(index=False):
            task_id = str(row.uid)
            if task_id not in requested:
                continue
            gold_document_ids = _resolve_officeqa_document_ids(
                str(row.source_files), documents_by_id
            )
            answers = _officeqa_answers(row.answer)
            prompt = str(row.question)
            source_hash = _hash_text(
                json.dumps(
                    [task_id, prompt, answers, gold_document_ids], ensure_ascii=False
                )
            )
            tasks[task_id] = TaskManifest(
                task_id=task_id,
                benchmark=benchmark,
                domain="document",
                prompt=prompt,
                gold_answers=answers,
                source_hash=source_hash,
                metadata={"gold_document_ids": gold_document_ids},
            )
    elif benchmark == "docvqa_10pct":
        frame = pd.read_parquet(data_root / config["dataset_path"])
        image_root = data_root / config.get(
            "image_dir", "materialized/docvqa_10pct/images"
        )
        for row in frame.itertuples(index=False):
            task_id = str(row.questionId)
            if task_id not in requested:
                continue
            image_path = image_root / f"{task_id}.png"
            if not image_path.is_file():
                raise FileNotFoundError(
                    f"materialized DocVQA image missing: {image_path}; "
                    "run scripts/materialize_docvqa_images.py"
                )
            answers = [str(value) for value in list(row.answers)]
            question_types = [str(value) for value in list(row.question_types)]
            prompt = str(row.question)
            source_hash = _hash_text(
                json.dumps(
                    [task_id, prompt, answers, sha256_file(image_path)],
                    ensure_ascii=False,
                )
            )
            tasks[task_id] = TaskManifest(
                task_id=task_id,
                benchmark=benchmark,
                domain="document",
                prompt=prompt,
                gold_answers=answers,
                source_hash=source_hash,
                artifact_path=str(image_path.resolve()),
                metadata={
                    "question_types": question_types,
                    "doc_id": str(row.docId),
                    "ucsf_document_id": str(row.ucsf_document_id),
                    "ucsf_document_page_no": str(row.ucsf_document_page_no),
                    "source_split": str(row.data_split),
                },
            )
    elif benchmark == "searchqa_skillopt":
        dataset_root = data_root / config["dataset_path"]
        for split_name in ("train", "val", "test"):
            items_path = dataset_root / split_name / "items.json"
            if not items_path.is_file():
                continue
            rows = json.loads(items_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError(f"expected SearchQA JSON array in {items_path}")
            for row in rows:
                task_id = str(row.get("id") or "")
                if task_id not in requested:
                    continue
                prompt = str(row.get("question") or "").strip()
                context = str(row.get("context") or "").strip()
                raw_answers = row.get("answers") or []
                answers = (
                    [str(value) for value in raw_answers]
                    if isinstance(raw_answers, list)
                    else [str(raw_answers)]
                )
                answers = [value for value in answers if value.strip()]
                if not prompt or not context or not answers:
                    raise ValueError(f"invalid SearchQA item: {task_id}")
                source_hash = _hash_text(
                    json.dumps(
                        [task_id, prompt, context, answers],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                tasks[task_id] = TaskManifest(
                    task_id=task_id,
                    benchmark=benchmark,
                    domain="document",
                    prompt=prompt,
                    gold_answers=answers,
                    source_hash=source_hash,
                    metadata={
                        "context": context,
                        "source_split": split_name,
                    },
                )
    elif benchmark == "dapo_fixed_1000":
        frame = pd.read_parquet(data_root / config["dataset_path"])
        for row in frame.itertuples(index=False):
            task_id = str(row.normalized_problem_hash)
            if task_id not in requested:
                continue
            reward = row.reward_model if isinstance(row.reward_model, dict) else {}
            tasks[task_id] = TaskManifest(
                task_id=task_id,
                benchmark=benchmark,
                domain="math",
                prompt=_prompt_text(row.prompt),
                gold_answers=[str(reward.get("ground_truth", ""))],
                source_hash=task_id,
            )
    elif benchmark == "livemathematicianbench":
        dataset_root = data_root / config["dataset_path"]
        files = (
            [dataset_root]
            if dataset_root.is_file()
            else sorted(dataset_root.glob("**/qa_*_final.json"))
        )
        for source_path in files:
            rows = json.loads(source_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError(f"expected JSON array in {source_path}")
            for row in rows:
                month = str(row.get("month", "")).strip()
                number = row.get("no")
                task_id = f"{month}:{number}"
                if task_id not in requested:
                    continue
                mcq = row.get("mcq") if isinstance(row.get("mcq"), dict) else {}
                prompt = str(mcq.get("question") or row.get("question") or "").strip()
                choices = mcq.get("choices") or row.get("choices") or []
                correct = mcq.get("correct_choice") or row.get("correct_choice") or {}
                if not prompt or not isinstance(choices, list) or not isinstance(correct, dict):
                    raise ValueError(f"invalid LiveMathematicianBench item: {task_id}")
                correct_text = str(correct.get("text") or "").strip()
                correct_label = str(correct.get("label") or "").strip()
                source_hash = _hash_text(
                    json.dumps(
                        [task_id, prompt, choices, correct],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                tasks[task_id] = TaskManifest(
                    task_id=task_id,
                    benchmark=benchmark,
                    domain="math",
                    prompt=prompt,
                    gold_answers=[correct_text or correct_label],
                    source_hash=source_hash,
                    metadata={
                        "month": month,
                        "no": number,
                        "paper_link": str(row.get("paper_link") or ""),
                        "theorem": str(row.get("theorem") or ""),
                        "sketch": str(row.get("sketch") or ""),
                        "theorem_type": list(row.get("theorem_type") or []),
                        "choices": choices,
                        "correct_choice": correct,
                        "source_path": str(source_path),
                        "group_id": str(row.get("paper_link") or task_id),
                    },
                )
    else:
        raise ValueError(f"unsupported evolution benchmark: {benchmark}")
    missing = [task_id for task_id in task_ids if task_id not in tasks]
    if missing:
        raise PairGenerationError(f"split task IDs are missing from data: {missing}")
    return [tasks[task_id] for task_id in task_ids]


def _resolve_split_path(raw_path: str | Path, data_root: Path) -> Path:
    split_path = Path(raw_path)
    if split_path.is_absolute():
        return split_path
    project_candidate = PROJECT_ROOT / split_path
    if project_candidate.is_file():
        return project_candidate
    relative_parts = split_path.parts
    if relative_parts and relative_parts[0] == "data":
        relative_parts = relative_parts[1:]
    return data_root.joinpath(*relative_parts)


def _instruction_evolution_record(
    task: TaskManifest,
    *,
    operator: str,
    severity: str,
    seed: int,
    generator_mode: str,
    client: DeepSeekClient | None,
) -> PairedNoiseRecord:
    op = _instruction_operator(operator)(
        model=client if generator_mode == "model" else None
    )
    result = op.generate(task, severity=severity, seed=seed, timing="evolution")
    noisy = task.model_copy(
        update={
            "prompt": str(result.payload["prompt"]),
            "source_hash": result.manifest.noisy_hash,
            "metadata": {
                **task.metadata,
                "noise_id": result.manifest.noise_id,
                "generator_mode": generator_mode,
            },
        }
    )
    return PairedNoiseRecord(
        task_id=task.task_id,
        operator=operator,
        clean=task,
        noisy=noisy,
        noise=result.manifest,
        validation=result.validation,
    )


def _spreadsheet_evolution_record(
    task: TaskManifest,
    *,
    operator: str,
    severity: str,
    seed: int,
    run_dir: Path,
) -> PairedNoiseRecord:
    native = SpreadsheetTask.from_paths(
        task_id=task.task_id,
        workbook_path=Path(task.artifact_path or ""),
        gold_workbook_path=Path(task.metadata["gold_workbook_path"]),
        prompt=task.prompt,
        answer_sheet=str(task.metadata["answer_sheet"]),
        answer_range=str(task.metadata["answer_range"]),
    )
    function = {
        "stale_backup_sheet": inject_backup_sheet,
        "semantic_decoy_sheet": inject_semantic_decoy_sheet,
    }[operator]
    output = run_dir / "artifacts" / f"{task.task_id}-{operator}-{severity}.xlsx"
    result = function(native, output, severity=severity, seed=seed)
    validation = validate_spreadsheet_noise(native, result)
    mechanism = "M4" if operator == "stale_backup_sheet" else "M1"
    noise = NoiseManifest(
        noise_id=f"{task.task_id}-C2-{mechanism}-{operator}-{severity}",
        task_id=task.task_id,
        channel="C2",
        mechanism=mechanism,
        operator=operator,
        domain=task.domain,
        benchmark=task.benchmark,
        severity=Severity(
            level=severity, budget={"L1": 1, "L2": 2, "L3": 3}[severity]
        ),
        seed=seed,
        clean_hash=task.source_hash,
        noisy_hash=result.noisy_hash,
        timing="evolution",
    )
    noisy = task.model_copy(
        update={
            "source_hash": result.noisy_hash,
            "artifact_path": str(output),
            "metadata": {**task.metadata, "noise_id": noise.noise_id},
        }
    )
    return PairedNoiseRecord(
        task_id=task.task_id,
        operator=operator,
        clean=task,
        noisy=noisy,
        noise=noise,
        validation=validation,
        artifact_path=str(output),
    )


def _officeqa_evolution_record(
    task: TaskManifest,
    *,
    config: dict[str, Any],
    data_root: Path,
    operator: str,
    severity: str,
    seed: int,
    run_dir: Path,
    documents: list[Any],
    decoy_index: Any,
) -> PairedNoiseRecord:
    native = OfficeQATask(
        task_id=task.task_id,
        question=task.prompt,
        answers=task.gold_answers,
        gold_document_id=str(task.metadata["gold_document_ids"][0]),
        source_document_ids=list(task.metadata["gold_document_ids"][1:]),
    )
    decoys = select_decoy_documents(
        native, documents, limit=8, index=decoy_index
    )
    gold_rank = 1 if operator == "semantic_decoy_document" else _officeqa_gold_rank(
        config, severity
    )
    fixture = build_rank_fixture(native, decoys=decoys, gold_rank=gold_rank)
    validation = validate_officeqa_noise(native, fixture)
    fixture_path = (
        run_dir / "retrieval_fixtures" / f"{task.task_id}-{operator}-{severity}.json"
    )
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(fixture.model_dump_json(indent=2) + "\n", encoding="utf-8")
    channel = "C2" if operator == "semantic_decoy_document" else "C3"
    mechanism = "M1" if operator == "semantic_decoy_document" else "M5"
    noise = NoiseManifest(
        noise_id=f"{task.task_id}-{channel}-{mechanism}-{operator}-{severity}",
        task_id=task.task_id,
        channel=channel,
        mechanism=mechanism,
        operator=operator,
        domain=task.domain,
        benchmark=task.benchmark,
        severity=Severity(
            level=severity,
            budget=(len(decoys) if gold_rank == 1 else gold_rank - 1),
        ),
        seed=seed,
        clean_hash=task.source_hash,
        noisy_hash=fixture.fixture_hash,
        timing="evolution",
    )
    noisy = task.model_copy(
        update={
            "source_hash": fixture.fixture_hash,
            "artifact_path": str(fixture_path),
            "metadata": {
                **task.metadata,
                "retrieval_fixture": str(fixture_path),
                "noise_id": noise.noise_id,
            },
        }
    )
    return PairedNoiseRecord(
        task_id=task.task_id,
        operator=operator,
        clean=task,
        noisy=noisy,
        noise=noise,
        validation=validation,
        artifact_path=str(fixture_path),
    )


def _math_evolution_record(
    task: TaskManifest,
    *,
    severity: str,
    seed: int,
    client: DeepSeekClient,
    max_attempts: int,
) -> PairedNoiseRecord:
    candidate = generate_flawed_solution(
        problem=task.prompt,
        gold_answer=task.gold_answers[0],
        task_hash=task.source_hash,
        client=client,
        severity=severity,
        seed=seed,
        max_attempts=max_attempts,
    )
    validation = validate_flawed_solution(candidate, task.gold_answers[0])
    noisy_prompt = wrap_failed_attempt(task.prompt, candidate.full_text)
    noisy_hash = _hash_text(noisy_prompt)
    noise = NoiseManifest(
        noise_id=f"{task.task_id}-C1-M2-flawed_partial_solution-{severity}",
        task_id=task.task_id,
        channel="C1",
        mechanism="M2",
        operator="flawed_partial_solution",
        domain=task.domain,
        benchmark=task.benchmark,
        severity=Severity(level=severity, budget=1),
        seed=seed,
        clean_hash=task.source_hash,
        noisy_hash=noisy_hash,
        generator_mode=GeneratorMode.model,
        timing="evolution",
        template_version="math-flaw-v4-short-single-error",
    )
    noisy = task.model_copy(
        update={
            "prompt": noisy_prompt,
            "source_hash": noisy_hash,
            "metadata": {
                **task.metadata,
                "noise_id": noise.noise_id,
                "math_candidate": candidate.model_dump(),
            },
        }
    )
    return PairedNoiseRecord(
        task_id=task.task_id,
        operator="flawed_partial_solution",
        clean=task,
        noisy=noisy,
        noise=noise,
        validation=validation,
    )


def _searchqa_evolution_record(
    task: TaskManifest,
    *,
    severity: str,
    seed: int,
    client: DeepSeekClient,
) -> PairedNoiseRecord:
    candidate = generate_semantic_decoy_evidence(
        task,
        client=client,
        severity=severity,
        seed=seed,
    )
    result = inject_semantic_decoy_evidence(
        task,
        candidate,
        severity=severity,
        seed=seed,
    )
    noise = NoiseManifest(
        noise_id=f"{task.task_id}-C2-M1-semantic_decoy_evidence-{severity}",
        task_id=task.task_id,
        channel="C2",
        mechanism="M1",
        operator="semantic_decoy_evidence",
        domain=task.domain,
        benchmark=task.benchmark,
        severity=Severity(level=severity, budget=len(candidate.decoy_passages)),
        seed=seed,
        clean_hash=task.source_hash,
        noisy_hash=result.noisy_hash,
        generator_mode=GeneratorMode.model,
        timing="evolution",
        template_version=SEARCHQA_EVIDENCE_TEMPLATE_VERSION,
    )
    noisy = task.model_copy(
        update={
            "source_hash": result.noisy_hash,
            "metadata": {
                **task.metadata,
                "context": result.noisy_context,
                "noise_id": noise.noise_id,
                "searchqa_decoy_candidate": candidate.model_dump(),
            },
        }
    )
    return PairedNoiseRecord(
        task_id=task.task_id,
        operator="semantic_decoy_evidence",
        clean=task,
        noisy=noisy,
        noise=noise,
        validation=result.validation,
    )


def _order_task_pool(
    task_ids: list[str],
    tasks_by_id: dict[str, TaskManifest],
    order: str,
    *,
    excluded_task_ids: set[str] | None = None,
) -> list[str]:
    """Apply a label-free, deterministic ordering within a frozen partition."""
    excluded = excluded_task_ids or set()
    available = [task_id for task_id in task_ids if task_id not in excluded]
    normalized = str(order or "manifest").strip().lower()
    if normalized in {"", "manifest"}:
        return available
    if normalized not in {"prompt_length_desc", "context_length_desc"}:
        raise PairGenerationError(f"unsupported task selection order: {order}")
    missing = [task_id for task_id in available if task_id not in tasks_by_id]
    if missing:
        raise PairGenerationError(f"selection tasks missing from dataset: {missing[:3]}")
    if normalized == "prompt_length_desc":
        length = lambda task_id: len(tasks_by_id[task_id].prompt)
    else:
        length = lambda task_id: len(
            str(tasks_by_id[task_id].metadata.get("context") or "")
        )
    return sorted(available, key=lambda task_id: (-length(task_id), task_id))


def generate_evolution_pairs_from_profile(
    profile_path: Path | str, *, offline: bool = False
) -> EvolutionGenerationSummary:
    """Generate one immutable clean/noisy evolution split from a frozen split."""
    load_dotenv(PROJECT_ROOT / ".env")
    profile = Path(profile_path)
    config = yaml.safe_load(profile.read_text(encoding="utf-8"))
    data_root = Path(os.environ.get("RSEBENCH_DATA_ROOT", PROJECT_ROOT / "data"))
    output_root = Path(
        os.environ.get("RSEBENCH_OUTPUT_ROOT", PROJECT_ROOT / "outputs")
    )
    split_path = _resolve_split_path(config["split_manifest"], data_root)
    split_raw = json.loads(split_path.read_text(encoding="utf-8"))
    sizes = dict(config.get("sizes") or {})
    partitions = dict(config.get("partitions") or {})
    train_partition = str(partitions.get("train", "evolution"))
    validation_partition = str(partitions.get("validation", "validation"))
    test_partition = str(partitions.get("clean_test", "test"))
    train_size = int(sizes.get("train", 10))
    validation_size = int(sizes.get("validation", 5))
    test_size = int(sizes.get("clean_test", 10))
    train_pool = [str(value) for value in split_raw[train_partition]]
    validation_pool = [str(value) for value in split_raw[validation_partition]]
    test_pool = [str(value) for value in split_raw[test_partition]]
    selection = dict(config.get("selection") or {})
    selection_order = str(selection.get("order", "manifest"))
    test_selection_order = str(selection.get("test_order", selection_order))
    excluded_task_ids = {
        str(task_id) for task_id in selection.get("exclude_task_ids", [])
    }
    preloaded_tasks: list[TaskManifest] | None = None
    if selection_order.strip().lower() not in {"", "manifest"}:
        candidate_ids = list(
            dict.fromkeys(train_pool + validation_pool + test_pool)
        )
        preloaded_tasks = _load_evolution_tasks(config, data_root, candidate_ids)
        candidate_by_id = {task.task_id: task for task in preloaded_tasks}
        train_pool = _order_task_pool(
            train_pool,
            candidate_by_id,
            selection_order,
            excluded_task_ids=excluded_task_ids,
        )
        validation_pool = _order_task_pool(
            validation_pool,
            candidate_by_id,
            selection_order,
            excluded_task_ids=excluded_task_ids,
        )
        test_pool = _order_task_pool(
            test_pool,
            candidate_by_id,
            test_selection_order,
            excluded_task_ids=excluded_task_ids,
        )
    elif excluded_task_ids:
        train_pool = [item for item in train_pool if item not in excluded_task_ids]
        validation_pool = [
            item for item in validation_pool if item not in excluded_task_ids
        ]
        test_pool = [item for item in test_pool if item not in excluded_task_ids]
    backfill = bool(selection.get("backfill_on_gate_rejection", False))
    candidate_multiplier = max(1, int(selection.get("candidate_multiplier", 1)))
    train_candidate_size = train_size * candidate_multiplier if backfill else train_size
    validation_candidate_size = (
        validation_size * candidate_multiplier if backfill else validation_size
    )
    train_candidate_ids = train_pool[:train_candidate_size]
    validation_offset = (
        train_candidate_size if validation_partition == train_partition else 0
    )
    validation_candidate_ids = validation_pool[
        validation_offset : validation_offset + validation_candidate_size
    ]
    test_ids = test_pool[:test_size]
    if (
        len(train_candidate_ids) < train_size
        or len(validation_candidate_ids) < validation_size
        or len(test_ids) != test_size
    ):
        raise PairGenerationError("configured pilot partition is smaller than requested")
    if set(train_candidate_ids + validation_candidate_ids) & set(test_ids):
        raise PairGenerationError("frozen split leaks evolution IDs into clean_test")
    all_tasks = preloaded_tasks or _load_evolution_tasks(
        config,
        data_root,
        train_candidate_ids + validation_candidate_ids + test_ids,
    )
    by_id = {task.task_id: task for task in all_tasks}
    operator = str(config["operator"])
    generator_mode = str(config.get("generator_mode", "rule"))
    severity = str(config.get("severity", "L2"))
    seed = int(config.get("seed", split_raw.get("seed", 0)))
    needs_model = generator_mode == "model" or operator == "flawed_partial_solution"
    client: DeepSeekClient | None = None
    if needs_model and not offline:
        client = DeepSeekClient.from_yaml(PROJECT_ROOT / config["model_config"])
    run_id = _run_id(profile, offline)
    run_dir = create_run_directory(output_root, "evolution-noise", run_id)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    records: list[PairedNoiseRecord] = []
    errors: list[str] = []
    office_documents: list[Any] | None = None
    office_decoy_index: Any = None
    if str(config["benchmark"]) == "officeqa_full" and operator not in {
        "failed_attempt",
        "related_distractor",
        "redundant_context",
    }:
        office_documents = _cached_officeqa_documents(
            data_root / config["corpus_path"]
        )
        office_decoy_index = build_decoy_index(
            office_documents,
            vocabulary=build_question_vocabulary(
                [
                    by_id[task_id].prompt
                    for task_id in train_candidate_ids + validation_candidate_ids
                ]
            ),
        )

    def generate_record(task_id: str) -> PairedNoiseRecord:
        task = by_id[task_id]
        if operator == "semantic_decoy_evidence" and client is not None:
            if task.benchmark != "searchqa_skillopt":
                raise ValueError(
                    "semantic_decoy_evidence currently requires searchqa_skillopt"
                )
            return _searchqa_evolution_record(
                task,
                severity=severity,
                seed=seed,
                client=client,
            )
        if operator in {"failed_attempt", "related_distractor", "redundant_context"}:
            if generator_mode == "model" and client is None:
                raise RuntimeError("model-backed operator disabled by --offline")
            return _instruction_evolution_record(
                task,
                operator=operator,
                severity=severity,
                seed=seed,
                generator_mode=generator_mode,
                client=client,
            )
        if task.domain == "spreadsheet":
            return _spreadsheet_evolution_record(
                task,
                operator=operator,
                severity=severity,
                seed=seed,
                run_dir=run_dir,
            )
        if task.benchmark == "officeqa_full":
            return _officeqa_evolution_record(
                task,
                config=config,
                data_root=data_root,
                operator=operator,
                severity=severity,
                seed=seed,
                run_dir=run_dir,
                documents=office_documents or [],
                decoy_index=office_decoy_index,
            )
        if operator == "flawed_partial_solution" and client is not None:
            return _math_evolution_record(
                task,
                severity=severity,
                seed=seed,
                client=client,
                max_attempts=int(config.get("generation", {}).get("max_attempts", 3)),
            )
        raise ValueError(f"unsupported evolution operator: {operator}")

    selected_train, attempted_train, train_rejections = _collect_gate_valid_records(
        train_candidate_ids,
        target_size=train_size,
        generate=generate_record,
    )
    selected_validation, attempted_validation, validation_rejections = (
        _collect_gate_valid_records(
            validation_candidate_ids,
            target_size=validation_size,
            generate=generate_record,
        )
    )
    records = attempted_train + attempted_validation
    gate_rejections = train_rejections + validation_rejections
    train_ids = [record.task_id for record in selected_train]
    validation_ids = [record.task_id for record in selected_validation]
    selected_records = selected_train + selected_validation
    if len(train_ids) != train_size or len(validation_ids) != validation_size:
        errors.append(
            "hard-gate candidate budget exhausted: "
            f"train={len(train_ids)}/{train_size}, "
            f"validation={len(validation_ids)}/{validation_size}"
        )
    if gate_rejections and not backfill:
        errors.extend(gate_rejections)

    pair_manifest: EvolutionSplitManifest | None = None
    pair_manifest_path: str | None = None
    if not errors:
        try:
            pair_manifest = assemble_evolution_split(
                benchmark=str(config["benchmark"]),
                domain=str(config["domain"]),
                seed=seed,
                source_hash=sha256_file(split_path),
                records=selected_records,
                train_ids=train_ids,
                validation_ids=validation_ids,
                clean_test=[by_id[task_id] for task_id in test_ids],
            )
        except PairGenerationError as exc:
            errors.append(str(exc))
    if pair_manifest is not None:
        manifest_file = run_dir / "pair_manifest.json"
        manifest_file.write_text(
            pair_manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        pair_manifest_path = str(manifest_file)
    summary = EvolutionGenerationSummary(
        run_id=run_id,
        run_dir=str(run_dir),
        profile=str(profile),
        operator=operator,
        offline=offline,
        status="generation_validated" if pair_manifest is not None else "rejected",
        records=records,
        errors=errors,
        gate_rejections=gate_rejections,
        pair_manifest=pair_manifest,
        pair_manifest_path=pair_manifest_path,
        selection_audit=EvolutionSelectionAudit(
            requested_sizes={
                "train": train_size,
                "validation": validation_size,
                "clean_test": test_size,
            },
            candidate_pool_sizes={
                "train": len(train_pool),
                "validation": len(validation_pool),
                "clean_test": len(test_pool),
            },
            candidate_budget_sizes={
                "train": len(train_candidate_ids),
                "validation": len(validation_candidate_ids),
            },
            candidate_ids={
                "train": train_candidate_ids,
                "validation": validation_candidate_ids,
            },
            selected_ids={"train": train_ids, "validation": validation_ids},
            test_ids=test_ids,
            excluded_ids=sorted(excluded_task_ids),
        ),
    )
    (run_dir / "summary.json").write_text(
        summary.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return summary
