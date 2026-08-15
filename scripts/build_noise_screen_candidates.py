#!/usr/bin/env python3
"""Build deterministic, portable noise-screen candidate manifests."""

from __future__ import annotations

import argparse
import ast
import csv
import itertools
import json
import math
import random
import re
import sys
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.contracts import TaskManifest  # noqa: E402
from rsebench.core1.dataset import (  # noqa: E402
    make_candidate_paths_portable,
    make_clean_split_paths_portable,
    make_confirmation_paths_portable,
    rehash_task,
    resolve_clean_split_paths,
)
from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
)
from rsebench.hashing import sha256_file  # noqa: E402
from rsebench.selection import ConfirmationSeal, ExposureRegistry  # noqa: E402
from rsebench.selection.splits import (  # noqa: E402
    CONFIRMATION_SKILLLEARN_FAMILIES,
    SCREENING_SKILLLEARN_FAMILIES,
    SelectionCandidateBundle,
    SelectionCounts,
    build_selection_candidates,
    build_skilllearn_selection_candidates,
)
from scripts.build_clean_skilllearn_qualification import _family_split  # noqa: E402


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}") from exc


def _resolve_config_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (config_path.parent / path).resolve()


def _load_fixture_bundles(
    config_path: Path,
    *,
    exposure_registry: ExposureRegistry,
    data_root: Path,
    methods_root: Path,
) -> dict[str, SelectionCandidateBundle]:
    payload = _load_json(config_path)
    benchmarks = payload.get("benchmarks")
    if not isinstance(benchmarks, Mapping) or not benchmarks:
        raise ValueError("source config requires a non-empty benchmarks mapping")
    bundles: dict[str, SelectionCandidateBundle] = {}
    for benchmark in sorted(benchmarks):
        row = benchmarks[benchmark]
        if not isinstance(row, Mapping):
            raise ValueError(f"source config benchmark {benchmark} must be a mapping")
        clean_path = _resolve_config_path(config_path, str(row["clean_split"]))
        clean = CleanEvolutionSplitManifest.model_validate(_load_json(clean_path))
        clean = resolve_clean_split_paths(
            clean,
            project_root=PROJECT_ROOT,
            data_root=data_root,
            methods_root=methods_root,
        )
        raw_pools = row.get("source_pools")
        if not isinstance(raw_pools, Mapping):
            raise ValueError(f"source config benchmark {benchmark} lacks source_pools")
        pools = {
            role: [
                TaskManifest.model_validate(task)
                for task in _load_json(
                    _resolve_config_path(config_path, str(raw_pools[role]))
                )
            ]
            for role in ("train", "validation", "test")
        }
        bundles[benchmark] = build_selection_candidates(
            clean_split=clean,
            source_pools=pools,
            exposure_registry=exposure_registry,
            counts=SelectionCounts.model_validate(row["counts"]),
        )
    return bundles


def _annotate_task(
    task: TaskManifest,
    *,
    n1_applicable: bool,
    n2_applicable: bool,
    metadata: Mapping[str, Any] | None = None,
) -> TaskManifest:
    return task.model_copy(
        update={
            "metadata": {
                **task.metadata,
                **(metadata or {}),
                "static_applicability": {
                    "N1": n1_applicable,
                    "N2": n2_applicable,
                },
            }
        },
        deep=True,
    )


def _load_clean_split(
    path: Path,
    *,
    data_root: Path,
    methods_root: Path,
) -> CleanEvolutionSplitManifest:
    split = CleanEvolutionSplitManifest.model_validate(_load_json(path))
    return resolve_clean_split_paths(
        split,
        project_root=PROJECT_ROOT,
        data_root=data_root,
        methods_root=methods_root,
    )


def _spreadsheet_task(
    row: Mapping[str, Any],
    *,
    dataset_root: Path,
) -> TaskManifest:
    task_id = str(row["id"])
    task_root = dataset_root / str(row["spreadsheet_path"])
    initial = next(iter(sorted(task_root.glob("*_init.xlsx"))), None)
    gold = next(iter(sorted(task_root.glob("*_golden.xlsx"))), None)
    initial = initial or (
        task_root / "initial.xlsx" if (task_root / "initial.xlsx").is_file() else None
    )
    gold = gold or (
        task_root / "golden.xlsx" if (task_root / "golden.xlsx").is_file() else None
    )
    if initial is None or gold is None:
        raise FileNotFoundError(f"Spreadsheet task artifacts are incomplete: {task_id}")
    task = TaskManifest(
        task_id=task_id,
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        prompt=str(row["instruction"]),
        verifier="spreadsheetbench_cell_range_v1",
        source_hash="0" * 64,
        artifact_path=str(initial.resolve()),
        metadata={
            "gold_workbook_path": str(gold.resolve()),
            "answer_sheet": str(row.get("answer_sheet", "")),
            "answer_range": str(row.get("answer_position", "")),
            "artifact_hash": sha256_file(initial),
            "gold_artifact_hash": sha256_file(gold),
            "static_applicability": {"N1": True, "N2": True},
        },
    )
    return rehash_task(task, artifact_hash=str(task.metadata["artifact_hash"]))


def _spreadsheet_bundle(
    *,
    exposure_registry: ExposureRegistry,
    data_root: Path,
    methods_root: Path,
) -> SelectionCandidateBundle:
    clean = _load_clean_split(
        PROJECT_ROOT
        / "benchmark/validation/clean_qualification_v2/spreadsheetbench_verified.json",
        data_root=data_root,
        methods_root=methods_root,
    )
    clean = clean.model_copy(
        update={
            role: [
                _annotate_task(task, n1_applicable=True, n2_applicable=True)
                for task in getattr(clean, role)
            ]
            for role in ("train", "validation", "clean_test")
        }
    )
    split = _load_json(
        data_root / "splits/spreadsheetbench_verified/split_manifest.json"
    )
    dataset_root = (
        data_root
        / "materialized/spreadsheetbench_verified/spreadsheetbench_verified_400"
    )
    rows = _load_json(dataset_root / "dataset.json")
    tasks = {
        str(row["id"]): _spreadsheet_task(row, dataset_root=dataset_root)
        for row in rows
    }
    pools = {
        "train": [tasks[str(task_id)] for task_id in split["evolution"]],
        "validation": [tasks[str(task_id)] for task_id in split["validation"]],
        "test": [tasks[str(task_id)] for task_id in split["test"]],
    }
    return build_selection_candidates(
        clean_split=clean,
        source_pools=pools,
        exposure_registry=exposure_registry,
        counts=SelectionCounts(train=20, validation=10, test=30),
    )


def _answers(value: str) -> list[str]:
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        parsed = None
    if isinstance(parsed, (list, tuple)):
        return [str(item) for item in parsed]
    return [value]


def _officeqa_task(
    row: Mapping[str, str],
    *,
    parsed_root: Path,
) -> TaskManifest:
    task_id = str(row["uid"])
    source_files = [
        value.strip() for value in str(row["source_files"]).splitlines() if value.strip()
    ]
    source_docs = [
        value.strip() for value in str(row["source_docs"]).splitlines() if value.strip()
    ]
    task = TaskManifest(
        task_id=task_id,
        benchmark="officeqa_full",
        domain="document",
        prompt=str(row["question"]),
        gold_answers=_answers(str(row["answer"])),
        source_hash="0" * 64,
        metadata={
            "gold_document_ids": source_files,
            "source_docs": source_docs,
            "difficulty": str(row["difficulty"]),
            "source_file_count": len(source_files),
            "officeqa_stratum": (
                f"difficulty={str(row['difficulty']).casefold()}|files={len(source_files)}"
            ),
            "parsed_page_root_path": str(parsed_root.resolve()),
            "scorer": "officeqa_released_numeric_v1",
            "scorer_tolerance": 0.01,
            "static_applicability": {
                "N1": True,
                "N2": bool(source_files),
            },
        },
    )
    return rehash_task(task)


def _officeqa_bundle(
    *,
    exposure_registry: ExposureRegistry,
    data_root: Path,
    methods_root: Path,
) -> SelectionCandidateBundle:
    clean = _load_clean_split(
        PROJECT_ROOT / "benchmark/validation/clean_qualification_v2/officeqa_full.json",
        data_root=data_root,
        methods_root=methods_root,
    )
    clean = clean.model_copy(
        update={
            role: [
                _annotate_task(
                    task,
                    n1_applicable=True,
                    n2_applicable=bool(task.metadata.get("gold_document_ids")),
                    metadata={
                        "officeqa_stratum": (
                            f"difficulty={str(task.metadata.get('difficulty', '')).casefold()}"
                            f"|files={int(task.metadata.get('source_file_count', 0))}"
                        )
                    },
                )
                for task in getattr(clean, role)
            ]
            for role in ("train", "validation", "clean_test")
        }
    )
    parsed_root = data_root / "materialized/officeqa_full/parsed"
    with (data_root / "materialized/officeqa_full/officeqa_full.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    tasks = [
        _officeqa_task(row, parsed_root=parsed_root)
        for row in rows
        if str(row["uid"]) != "UID0240"
        and bool(str(row["source_files"]).strip())
    ]
    pools = {role: tasks for role in ("train", "validation", "test")}
    return build_selection_candidates(
        clean_split=clean,
        source_pools=pools,
        exposure_registry=exposure_registry,
        counts=SelectionCounts(train=12, validation=12, test=20),
    )


def _normalized_query(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def _webshop_goals(methods_root: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    webshop_root = methods_root / "webshop"
    products = _load_json(webshop_root / "data/items_shuffle_1000.json")[:1000]
    attributes = _load_json(webshop_root / "data/items_ins_v2_1000.json")
    seen_asins: set[str] = set()
    cleaned_products: list[dict[str, Any]] = []
    goals: list[dict[str, Any]] = []
    for product in products:
        asin = str(product.get("asin", ""))
        if not asin or asin == "nan" or len(asin) > 10 or asin in seen_asins:
            continue
        seen_asins.add(asin)
        detail = attributes.get(asin, {})
        instruction = detail.get("instruction")
        instruction_attributes = detail.get("instruction_attributes")
        product = dict(product)
        product["Attributes"] = list(detail.get("attributes") or ["DUMMY_ATTR"])
        cleaned_products.append(product)
        if instruction is None or not instruction_attributes:
            continue
        options: dict[str, list[str]] = {}
        for option_name, values in (product.get("customization_options") or {}).items():
            if values is None:
                continue
            options[str(option_name).casefold()] = [
                str(value["value"]).strip().replace("/", " | ").casefold()
                for value in values
            ]
        option_names = sorted(options)
        combinations = list(
            itertools.product(*(options[name] for name in option_names))
        )
        for combination in combinations:
            goal_options = dict(zip(option_names, combination, strict=True))
            option_text = ", and ".join(
                f"{name}: {value}" for name, value in goal_options.items()
            )
            option_text = f" with {option_text}" if option_text else ""
            pricing = str(product.get("pricing") or "")
            prices = [float(value) for value in re.findall(r"[0-9]+(?:\.[0-9]+)?", pricing)]
            price = prices[0] if prices else 100.0
            price_upper = 10.0 * max(1, math.ceil((price + 0.01) / 10.0))
            goals.append(
                {
                    "asin": asin,
                    "query": str(product.get("query", "")).casefold().strip(),
                    "instruction_text": (
                        f"{instruction}{option_text}, and price lower than "
                        f"{price_upper:.2f} dollars"
                    ),
                    "attributes": list(instruction_attributes),
                    "goal_options": goal_options,
                    "price_upper": price_upper,
                }
            )
    random.Random(233).shuffle(goals)
    query_groups: dict[str, list[str]] = {}
    for product in cleaned_products:
        query_groups.setdefault(_normalized_query(product.get("query", "")), []).append(
            str(product["asin"])
        )
    ranks: dict[str, int] = {}
    for index, goal in enumerate(goals):
        group = query_groups.get(_normalized_query(goal["query"]), [])
        if goal["asin"] in group:
            ranks[str(index)] = group.index(goal["asin"])
    return goals, ranks


def _webshop_task(
    goal_index: int,
    goal: Mapping[str, Any],
    *,
    retrieval_rank: int,
) -> TaskManifest:
    constraint_count = (
        len(goal.get("attributes") or []) + len(goal.get("goal_options") or {}) + 1
    )
    task = TaskManifest(
        task_id=f"goal_{goal_index}",
        benchmark="webshop",
        domain="interactive",
        prompt=str(goal["instruction_text"]),
        verifier="webshop_official_reward_v1",
        source_hash="0" * 64,
        metadata={
            "goal_idx": goal_index,
            "target_asin": str(goal["asin"]),
            "query": str(goal["query"]),
            "normalized_query": _normalized_query(goal["query"]),
            "target_reachable": retrieval_rank < 10,
            "option_count": len(goal.get("goal_options") or {}),
            "constraint_count": constraint_count,
            "retrieval_rank": retrieval_rank,
            "static_applicability": {
                "N1": constraint_count >= 2,
                "N2": retrieval_rank < 10,
            },
        },
    )
    return rehash_task(task)


def _webshop_bundle(
    *,
    exposure_registry: ExposureRegistry,
    data_root: Path,
    methods_root: Path,
) -> SelectionCandidateBundle:
    clean = _load_clean_split(
        PROJECT_ROOT / "benchmark/validation/clean_qualification_v2/webshop.json",
        data_root=data_root,
        methods_root=methods_root,
    )
    selection = _load_json(
        PROJECT_ROOT
        / "benchmark/validation/clean_qualification_v1/webshop_validation_selection.json"
    )
    scores = {
        int(task_id): float(score)
        for task_id, score in selection["candidate_seed_scores"].items()
    }
    goals, ranks = _webshop_goals(methods_root)
    clean_ids = {
        int(task.metadata["goal_idx"])
        for task in list(clean.train) + list(clean.validation) + list(clean.clean_test)
    }

    def annotate_clean(task: TaskManifest) -> TaskManifest:
        index = int(task.metadata["goal_idx"])
        goal = goals[index]
        rank = ranks.get(str(index), 10_000)
        detail = _webshop_task(index, goal, retrieval_rank=rank).metadata
        metadata = dict(detail)
        if index in scores:
            metadata["seed_success"] = scores[index] == 1.0
        return task.model_copy(update={"metadata": metadata}, deep=True)

    clean = clean.model_copy(
        update={
            role: [annotate_clean(task) for task in getattr(clean, role)]
            for role in ("train", "validation", "clean_test")
        }
    )
    used_queries = {
        str(task.metadata["normalized_query"])
        for task in list(clean.train) + list(clean.validation) + list(clean.clean_test)
    }

    def partition(start: int, stop: int) -> list[TaskManifest]:
        selected: list[TaskManifest] = []
        for index in range(start, min(stop, len(goals))):
            if index in clean_ids:
                continue
            rank = ranks.get(str(index))
            if rank is None or rank >= 10:
                continue
            task = _webshop_task(index, goals[index], retrieval_rank=rank)
            query = str(task.metadata["normalized_query"])
            if not query or query in used_queries:
                continue
            used_queries.add(query)
            selected.append(task)
        return selected

    # Test requires the largest reserved pool. Allocate its unique queries
    # before the smaller validation and train pools so later roles cannot
    # consume its finite official-partition vocabulary.
    test_pool = partition(0, 500)
    validation_pool = partition(500, 1500)
    train_pool = partition(1500, len(goals))
    pools = {
        "train": train_pool,
        "validation": validation_pool,
        "test": test_pool,
    }
    return build_selection_candidates(
        clean_split=clean,
        source_pools=pools,
        exposure_registry=exposure_registry,
        counts=SelectionCounts(train=5, validation=5, test=20),
    )


def _skilllearn_bundle(
    *,
    exposure_registry: ExposureRegistry,
    data_root: Path,
    methods_root: Path,
) -> SelectionCandidateBundle:
    root = PROJECT_ROOT / "benchmark/validation/clean_qualification_v2/skilllearnbench"
    screening = {
        family: CleanEvolutionSplitManifest.model_validate(
            _load_json(root / f"{family}.json")
        )
        for family in SCREENING_SKILLLEARN_FAMILIES
    }
    confirmation = {
        family: make_clean_split_paths_portable(
            _family_split(
                family,
                qualification_version="noise-screen-v1",
                methods_root=methods_root,
            ),
            project_root=PROJECT_ROOT,
            data_root=data_root,
            methods_root=methods_root,
        )
        for family in CONFIRMATION_SKILLLEARN_FAMILIES
    }
    return build_skilllearn_selection_candidates(
        screening_splits=screening,
        confirmation_splits=confirmation,
        exposure_registry=exposure_registry,
        official_tasks_root=methods_root / "skilllearnbench/tasks",
    )


def load_repository_bundles(
    *,
    exposure_registry: ExposureRegistry,
    data_root: Path,
    methods_root: Path,
) -> dict[str, SelectionCandidateBundle]:
    """Load only pinned local benchmark resources; never contact a provider."""

    if not data_root.is_dir():
        raise FileNotFoundError(f"data root does not exist: {data_root}")
    if not methods_root.is_dir():
        raise FileNotFoundError(f"methods root does not exist: {methods_root}")
    return {
        "spreadsheetbench_verified": _spreadsheet_bundle(
            exposure_registry=exposure_registry,
            data_root=data_root,
            methods_root=methods_root,
        ),
        "officeqa_full": _officeqa_bundle(
            exposure_registry=exposure_registry,
            data_root=data_root,
            methods_root=methods_root,
        ),
        "webshop": _webshop_bundle(
            exposure_registry=exposure_registry,
            data_root=data_root,
            methods_root=methods_root,
        ),
        "skilllearnbench": _skilllearn_bundle(
            exposure_registry=exposure_registry,
            data_root=data_root,
            methods_root=methods_root,
        ),
    }


def _portable_bundle(
    bundle: SelectionCandidateBundle,
    *,
    exposure_registry: ExposureRegistry,
    data_root: Path,
    methods_root: Path,
) -> SelectionCandidateBundle:
    candidates = [
        make_candidate_paths_portable(
            candidate,
            project_root=PROJECT_ROOT,
            data_root=data_root,
            methods_root=methods_root,
        )
        for candidate in bundle.candidates
    ]
    confirmation = make_confirmation_paths_portable(
        bundle.confirmation,
        project_root=PROJECT_ROOT,
        data_root=data_root,
        methods_root=methods_root,
    )
    confirmation_roles = {
        "train": list(confirmation.train),
        "validation": list(confirmation.validation),
        "confirmation_test": list(confirmation.confirmation_test),
    }
    seal = ConfirmationSeal(
        created_before_screening=True,
        split_hashes={
            role: canonical_hash([task.model_dump(mode="json") for task in tasks])
            for role, tasks in confirmation_roles.items()
        },
        task_ids={
            role: [task.task_id for task in tasks]
            for role, tasks in confirmation_roles.items()
        },
        exposure_registry_hash=exposure_registry.registry_hash,
    )
    return SelectionCandidateBundle(
        benchmark=bundle.benchmark,
        candidates=candidates,
        confirmation=confirmation,
        confirmation_seal=seal,
    )


def _serialize(payload: Any) -> bytes:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    else:
        payload = _json_value(payload)
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(child) for child in value]
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    return value


def _write_immutable(path: Path, payload: Any) -> None:
    encoded = _serialize(payload)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(
                f"different candidate manifest already exists: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def _global_seal(
    bundles: Mapping[str, SelectionCandidateBundle],
    exposure_registry: ExposureRegistry,
) -> ConfirmationSeal:
    split_hashes: dict[str, str] = {}
    task_ids: dict[str, list[str]] = {}
    for benchmark in sorted(bundles):
        bundle = bundles[benchmark]
        for role, digest in bundle.confirmation_seal.split_hashes.items():
            split_hashes[f"{benchmark}:{role}"] = digest
        for role, ids in bundle.confirmation_seal.task_ids.items():
            task_ids[f"{benchmark}:{role}"] = list(ids)
    return ConfirmationSeal(
        created_before_screening=True,
        split_hashes=split_hashes,
        task_ids=task_ids,
        exposure_registry_hash=exposure_registry.registry_hash,
    )


def write_bundles(
    bundles: Mapping[str, SelectionCandidateBundle],
    *,
    exposure_registry: ExposureRegistry,
    output_root: Path,
) -> None:
    candidate_index: dict[str, list[str]] = {}
    candidate_audits: dict[str, list[str]] = {}
    confirmations: dict[str, str] = {}
    for benchmark in sorted(bundles):
        bundle = bundles[benchmark]
        candidate_paths = []
        audit_paths = []
        for candidate in bundle.candidates:
            relative = Path("candidates") / benchmark / (
                f"candidate_{candidate.candidate_index}.json"
            )
            _write_immutable(output_root / relative, candidate)
            candidate_paths.append(relative.as_posix())
            audit_relative = Path("candidate_audits") / benchmark / (
                f"candidate_{candidate.candidate_index}.json"
            )
            _write_immutable(
                output_root / audit_relative,
                {
                    "schema_version": "rsebench.selection-candidate-audit.v1",
                    "benchmark": benchmark,
                    "candidate_index": candidate.candidate_index,
                    "selection_hash": candidate.selection_hash,
                    "static_gates": candidate.metadata["static_audit"],
                },
            )
            audit_paths.append(audit_relative.as_posix())
        confirmation_path = Path("confirmation") / f"{benchmark}.json"
        _write_immutable(output_root / confirmation_path, bundle.confirmation)
        candidate_index[benchmark] = candidate_paths
        candidate_audits[benchmark] = audit_paths
        confirmations[benchmark] = confirmation_path.as_posix()
    global_seal = _global_seal(bundles, exposure_registry)
    _write_immutable(output_root / "confirmation_seal.json", global_seal)
    manifest = {
        "schema_version": "rsebench.selection-candidate-index.v1",
        "selection_version": "noise-screen-v1",
        "candidates": candidate_index,
        "candidate_audits": candidate_audits,
        "confirmation": confirmations,
        "confirmation_seal": "confirmation_seal.json",
        "exposure_registry_hash": exposure_registry.registry_hash,
        "ordered_benchmarks": sorted(bundles),
    }
    _write_immutable(output_root / "manifest.json", manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exposure", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--methods-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--source-config",
        type=Path,
        help="test/development override for explicit clean and source task JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = ExposureRegistry.model_validate(_load_json(args.exposure))
    data_root = args.data_root.resolve()
    methods_root = args.methods_root.resolve()
    if args.source_config is None:
        bundles = load_repository_bundles(
            exposure_registry=registry,
            data_root=data_root,
            methods_root=methods_root,
        )
    else:
        bundles = _load_fixture_bundles(
            args.source_config.resolve(),
            exposure_registry=registry,
            data_root=data_root,
            methods_root=methods_root,
        )
    portable = {
        benchmark: _portable_bundle(
            bundle,
            exposure_registry=registry,
            data_root=data_root,
            methods_root=methods_root,
        )
        for benchmark, bundle in bundles.items()
    }
    write_bundles(portable, exposure_registry=registry, output_root=args.output)
    candidate_count = sum(len(bundle.candidates) for bundle in portable.values())
    print(
        f"Wrote {candidate_count} candidates for {len(portable)} benchmarks; "
        "provider_calls=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
