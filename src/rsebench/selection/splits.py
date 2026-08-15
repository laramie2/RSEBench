"""Deterministic provider-free candidate and confirmation split generation."""

from __future__ import annotations

import re
import tomllib
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel, TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.selection.contracts import (
    ConfirmationSeal,
    ConfirmationSplit,
    ExposureLevel,
    ExposureRegistry,
    StableSplitCandidate,
    selection_key,
)


SCREENING_SKILLLEARN_FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
)
CONFIRMATION_SKILLLEARN_FAMILIES = (
    "court-form-filling",
    "earthquake-plate-calculation",
    "dbscan-parameter-tuning",
    "travel-planning",
)
DEFAULT_SKILLLEARN_TASKS_ROOT = (
    Path(__file__).resolve().parents[3]
    / "methods/external/skilllearnbench/tasks"
)
_SKILLLEARN_N1_TARGETS = {
    "organize-messy-files": "fixed_filename_rules",
    "offer-letter-generator": "fixed_filename_rules",
    "schedule-planning": "fixed_document_coordinates",
    "dependency-vulnerability-check": "fixed_software_configuration",
    "github-repo-analytics": "fixed_software_configuration",
    "financial-analysis": "fixed_spreadsheet_columns",
    "stock-data-visualization": "fixed_spreadsheet_columns",
    "enterprise-information-search": "fixed_instance_constants",
}
_SKILLLEARN_N2_TARGET_SUFFIXES = {
    "organize-messy-files": frozenset({".docx", ".pdf", ".pptx", ".txt"}),
    "offer-letter-generator": frozenset({".docx", ".pdf", ".pptx", ".txt"}),
    "schedule-planning": frozenset({".pdf"}),
    "dependency-vulnerability-check": frozenset(
        {".json", ".lock", ".py", ".toml", ".yaml", ".yml"}
    ),
    "github-repo-analytics": frozenset(
        {".json", ".lock", ".py", ".toml", ".yaml", ".yml"}
    ),
    "financial-analysis": frozenset({".csv", ".json", ".tsv", ".xlsx", ".zip"}),
    "stock-data-visualization": frozenset(
        {".csv", ".json", ".tsv", ".xlsx", ".zip"}
    ),
    "enterprise-information-search": frozenset({".json", ".txt"}),
}

SPREADSHEET_KEYWORD_MAP_VERSION = "spreadsheet-operation-keywords-v1"
SPREADSHEET_OPERATION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "lookup_join",
        (
            "lookup",
            "xlookup",
            "vlookup",
            "join",
            "match",
            "merge",
        ),
    ),
    (
        "aggregation_formula",
        (
            "sum",
            "sumif",
            "countif",
            "average",
            "formula",
            "subtotal",
        ),
    ),
    (
        "text_date_cleaning",
        (
            "clean",
            "date",
            "text",
            "trim",
            "extract",
            "split",
        ),
    ),
    (
        "layout_chart_pivot",
        (
            "layout",
            "chart",
            "pivot",
            "format",
            "style",
            "dashboard",
        ),
    ),
)


class SelectionCounts(StrictModel):
    """Exact train, validation, and test sizes for one benchmark."""

    train: int = Field(gt=0)
    validation: int = Field(gt=0)
    test: int = Field(gt=0)


class SelectionCandidateBundle(StrictModel):
    """All preregistered candidates plus the independently sealed split."""

    schema_version: str = "rsebench.selection-candidate-bundle.v1"
    benchmark: str
    candidates: list[StableSplitCandidate]
    confirmation: ConfirmationSplit
    confirmation_seal: ConfirmationSeal

    @property
    def screening_all_ids(self) -> list[str]:
        return list(
            dict.fromkeys(
                task.task_id
                for candidate in self.candidates
                for task in (
                    candidate.train
                    + candidate.validation
                    + candidate.qualification_test
                    + candidate.screening_test
                )
            )
        )

    @property
    def confirmation_all_ids(self) -> list[str]:
        row = self.confirmation
        return list(
            dict.fromkeys(
                task.task_id
                for task in row.train + row.validation + row.confirmation_test
            )
        )

    @property
    def screening_test_ids(self) -> list[str]:
        return [task.task_id for task in self.candidates[0].screening_test]

    @model_validator(mode="after")
    def validate_isolation(self) -> "SelectionCandidateBundle":
        if not self.candidates:
            raise ValueError("selection candidate bundle requires candidates")
        if any(candidate.benchmark != self.benchmark for candidate in self.candidates):
            raise ValueError("candidate benchmark differs from bundle benchmark")
        if self.confirmation.benchmark != self.benchmark:
            raise ValueError("confirmation benchmark differs from bundle benchmark")
        overlap = set(self.screening_all_ids) & set(self.confirmation_all_ids)
        if overlap:
            raise ValueError(
                f"screening and confirmation task IDs must be disjoint: {sorted(overlap)}"
            )
        return self


def round_robin_exact(
    groups: Mapping[str, Sequence[TaskManifest]], *, count: int
) -> list[TaskManifest]:
    """Take exactly ``count`` rows by cycling over sorted stratum names."""

    if count < 0:
        raise ValueError("count must be non-negative")
    queues = {name: deque(rows) for name, rows in sorted(groups.items())}
    selected: list[TaskManifest] = []
    while len(selected) < count:
        progressed = False
        for name in sorted(queues):
            if queues[name]:
                selected.append(queues[name].popleft())
                progressed = True
                if len(selected) == count:
                    return selected
        if not progressed:
            raise ValueError(f"insufficient eligible pool: requested {count}")
    return selected


def select_by_strata(
    tasks: Sequence[TaskManifest],
    *,
    count: int,
    benchmark: str,
    role: str,
    candidate_index: int,
    stratum: Callable[[TaskManifest], str],
    excluded_ids: set[str],
) -> list[TaskManifest]:
    """Hash-sort within strata and select by deterministic round robin."""

    groups: dict[str, list[TaskManifest]] = defaultdict(list)
    seen: set[str] = set()
    for task in tasks:
        if task.task_id in excluded_ids or task.task_id in seen:
            continue
        if task.benchmark != benchmark:
            raise ValueError(
                f"source task {task.task_id} benchmark differs from {benchmark}"
            )
        seen.add(task.task_id)
        groups[stratum(task)].append(task)
    for name, rows in groups.items():
        rows.sort(
            key=lambda task: (
                selection_key(
                    benchmark=benchmark,
                    role=role,
                    candidate_index=candidate_index,
                    stratum=name,
                    task_id=task.task_id,
                ),
                task.task_id,
            )
        )
    return round_robin_exact(groups, count=count)


def spreadsheet_operation_category(task: TaskManifest) -> str:
    """Classify spreadsheet prompts using the preregistered keyword map."""

    prompt = task.prompt.casefold()
    for category, keywords in SPREADSHEET_OPERATION_KEYWORDS:
        if any(keyword in prompt for keyword in keywords):
            return category
    return "other"


def _officeqa_question_axis(prompt: str) -> str:
    normalized = prompt.casefold()
    rules = (
        ("period", r"\b(?:year|quarter|month|week|period|fiscal|calendar|date)\b"),
        ("unit", r"\b(?:dollars?|millions?|billions?|percent|percentage|rate)\b"),
        (
            "entity",
            r"\b(?:who|agency|department|treasury|government|country|entity)\b",
        ),
        (
            "aggregation",
            r"\b(?:sum|total|average|mean|combined|difference|highest|lowest)\b",
        ),
    )
    for axis, pattern in rules:
        if re.search(pattern, normalized):
            return axis
    return "other"


def officeqa_stratum(task: TaskManifest) -> str:
    """Combine the released OfficeQA stratum with one question axis."""

    base = str(task.metadata.get("officeqa_stratum") or "").strip()
    if not base:
        difficulty = str(task.metadata.get("difficulty", "unknown")).casefold()
        source_count = int(task.metadata.get("source_file_count", 0))
        base = f"difficulty={difficulty}|files={source_count}"
    return f"{base}|axis={_officeqa_question_axis(task.prompt)}"


def _count_bin(value: int) -> str:
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    return "2+"


def _constraint_bin(value: int) -> str:
    if value <= 1:
        return "0-1"
    if value <= 3:
        return "2-3"
    return "4+"


def _rank_bin(value: int) -> str:
    if value <= 2:
        return "1-3"
    if value <= 5:
        return "4-6"
    return "7-10"


def webshop_stratum(task: TaskManifest) -> str:
    """Bin WebShop option, constraint, and one-based retrieval rank counts."""

    option_count = int(task.metadata.get("option_count", 0))
    constraint_count = int(task.metadata.get("constraint_count", 0))
    retrieval_rank = int(task.metadata.get("retrieval_rank", 0))
    return (
        f"options={_count_bin(option_count)}"
        f"|constraints={_constraint_bin(constraint_count)}"
        f"|rank={_rank_bin(retrieval_rank)}"
    )


def skilllearn_stratum(task: TaskManifest) -> str:
    return str(task.metadata.get("task_family") or task.task_id.rsplit("-", 1)[0])


def _domain_stratum(benchmark: str) -> Callable[[TaskManifest], str]:
    return {
        "spreadsheetbench_verified": spreadsheet_operation_category,
        "officeqa_full": officeqa_stratum,
        "webshop": webshop_stratum,
        "skilllearnbench": skilllearn_stratum,
    }.get(benchmark, lambda task: str(task.metadata.get("stratum", "all")))


def _ordered_ids(roles: Mapping[str, Sequence[TaskManifest]]) -> dict[str, list[str]]:
    return {
        role: [task.task_id for task in tasks]
        for role, tasks in roles.items()
    }


def _source_hash(roles: Mapping[str, Sequence[TaskManifest]]) -> str:
    return canonical_hash(
        {
            role: [task.model_dump(mode="json") for task in tasks]
            for role, tasks in roles.items()
        }
    )


def _batch_sizes(total: int, batch_size: int) -> list[int]:
    return [min(batch_size, total - start) for start in range(0, total, batch_size)]


def _noise_applicability(
    tasks: Sequence[TaskManifest],
) -> dict[str, dict[str, float | str | None]]:
    statuses: dict[str, dict[str, float | str | None]] = {}
    for stage in ("N1", "N2"):
        applicable = [
            task.metadata.get("static_applicability", {}).get(stage) is True
            for task in tasks
        ]
        coverage = sum(applicable) / len(applicable) if applicable else 0.0
        statuses[stage] = {
            "coverage": coverage,
            "status": "pass" if coverage == 1.0 else "fail",
        }
    for stage in ("N3", "N4"):
        statuses[stage] = {"coverage": None, "status": "pending"}
    return statuses


def _static_audit(
    *,
    benchmark: str,
    train: Sequence[TaskManifest],
    validation: Sequence[TaskManifest],
    test: Sequence[TaskManifest],
    require_recorded_headroom: bool = True,
) -> dict[str, Any]:
    acquisition = [*train, *validation]
    applicability = _noise_applicability(acquisition)
    if any(applicability[stage]["status"] != "pass" for stage in ("N1", "N2")):
        raise ValueError("N1/N2 static applicability must be 100%")
    audit: dict[str, Any] = {
        "noise_applicability": applicability,
        "ordered_task_ids": _ordered_ids(
            {"train": train, "validation": validation, "test": test}
        ),
    }
    if benchmark == "spreadsheetbench_verified":
        categories = sorted({spreadsheet_operation_category(task) for task in train})
        if len(categories) < 4:
            raise ValueError("Spreadsheet train must cover at least four operation categories")
        audit.update(
            {
                "keyword_map_version": SPREADSHEET_KEYWORD_MAP_VERSION,
                "operation_categories": categories,
                "train_batch_sizes": _batch_sizes(len(train), 7),
            }
        )
    elif benchmark == "officeqa_full":
        all_tasks = [*train, *validation, *test]
        if any(task.task_id == "UID0240" for task in all_tasks):
            raise ValueError("OfficeQA excludes UID0240")
        difficulties = sorted(
            {
                str(task.metadata.get("difficulty", "unknown")).casefold()
                for task in acquisition
            }
        )
        source_file_counts = sorted(
            {int(task.metadata.get("source_file_count", 0)) for task in acquisition}
        )
        question_axes = sorted(
            {_officeqa_question_axis(task.prompt) for task in acquisition}
        )
        if not {"easy", "hard"}.issubset(difficulties):
            raise ValueError("OfficeQA difficulty coverage requires easy and hard")
        if len(source_file_counts) < 2:
            raise ValueError(
                "OfficeQA source-file-count coverage requires two distinct counts"
            )
        if len(question_axes) < 4:
            raise ValueError(
                "OfficeQA question-axis coverage requires four distinct axes"
            )
        audit.update(
            {
                "difficulty_coverage": difficulties,
                "source_file_count_coverage": source_file_counts,
                "question_axis_coverage": question_axes,
                "coverage_gates": {
                    "difficulty": {
                        "required": ["easy", "hard"],
                        "status": "pass",
                    },
                    "source_file_count": {
                        "minimum_distinct": 2,
                        "status": "pass",
                    },
                    "question_axis": {
                        "minimum_distinct": 4,
                        "status": "pass",
                    },
                },
                "train_batch_sizes": _batch_sizes(len(train), 4),
            }
        )
    elif benchmark == "webshop":
        all_tasks = [*train, *validation, *test]
        queries = [
            str(task.metadata.get("normalized_query") or " ".join(
                str(task.metadata.get("query", "")).casefold().split()
            ))
            for task in all_tasks
        ]
        unique_queries = bool(all(queries)) and len(queries) == len(set(queries))
        reachable = all(task.metadata.get("target_reachable") is True for task in all_tasks)
        successes = sum(task.metadata.get("seed_success") is True for task in validation)
        if require_recorded_headroom and (successes, len(validation)) != (2, 5):
            raise ValueError("WebShop requires exactly 2/5 validation headroom")
        if not unique_queries:
            raise ValueError("WebShop normalized queries must be unique")
        if not reachable:
            raise ValueError("WebShop target ASINs must be reachable")
        audit.update(
            {
                "unique_normalized_queries": unique_queries,
                "reachable_target_asins": reachable,
                "validation_headroom": (
                    {"successes": successes, "total": 5}
                    if require_recorded_headroom
                    else {"status": "pending"}
                ),
                "train_batch_sizes": [len(train)],
            }
        )
    return audit


def _candidate(
    *,
    clean_split: CleanEvolutionSplitManifest,
    candidate_index: int,
    train: Sequence[TaskManifest],
    screening_test: Sequence[TaskManifest],
) -> StableSplitCandidate:
    roles = {
        "train": list(train),
        "validation": list(clean_split.validation),
        "qualification_test": list(clean_split.clean_test),
        "screening_test": list(screening_test),
    }
    audit = _static_audit(
        benchmark=clean_split.benchmark,
        train=roles["train"],
        validation=roles["validation"],
        test=roles["screening_test"],
    )
    source_metadata = {
        "source_seed": clean_split.seed,
        **{
            key: clean_split.metadata[key]
            for key in ("runtime", "baseline", "feedback_mode")
            if key in clean_split.metadata
        },
    }
    return StableSplitCandidate(
        benchmark=clean_split.benchmark,
        domain=clean_split.domain,
        candidate_index=candidate_index,
        source_hash=_source_hash(roles),
        selection_hash=canonical_hash(_ordered_ids(roles)),
        metadata={
            "qualification_version": "noise-screen-v1",
            "selection_version": "noise-screen-v1",
            "static_audit": audit,
            **source_metadata,
        },
        **roles,
    )


def _seal(
    confirmation: ConfirmationSplit,
    exposure_registry: ExposureRegistry,
) -> ConfirmationSeal:
    roles = {
        "train": list(confirmation.train),
        "validation": list(confirmation.validation),
        "confirmation_test": list(confirmation.confirmation_test),
    }
    return ConfirmationSeal(
        created_before_screening=True,
        split_hashes={
            role: canonical_hash([task.model_dump(mode="json") for task in tasks])
            for role, tasks in roles.items()
        },
        task_ids=_ordered_ids(roles),
        exposure_registry_hash=exposure_registry.registry_hash,
    )


def build_selection_candidates(
    *,
    clean_split: CleanEvolutionSplitManifest,
    source_pools: Mapping[str, Sequence[TaskManifest]],
    exposure_registry: ExposureRegistry,
    counts: SelectionCounts,
) -> SelectionCandidateBundle:
    """Build three train-only candidates after reserving confirmation."""

    benchmark = clean_split.benchmark
    if set(source_pools) != {"train", "validation", "test"}:
        raise ValueError("source_pools must contain exactly train, validation, and test")
    for role, tasks in source_pools.items():
        counts_by_id = Counter(task.task_id for task in tasks)
        duplicates = sorted(
            task_id for task_id, frequency in counts_by_id.items() if frequency > 1
        )
        if duplicates:
            raise ValueError(
                f"duplicate task IDs in source pool {role}: {duplicates}"
            )
    if (
        len(clean_split.train),
        len(clean_split.validation),
        len(clean_split.clean_test),
    ) != (counts.train, counts.validation, counts.test):
        raise ValueError("clean split does not match requested exact counts")
    if benchmark == "officeqa_full" and "UID0240" in {
        task.task_id
        for task in (
            list(clean_split.train)
            + list(clean_split.validation)
            + list(clean_split.clean_test)
        )
    }:
        raise ValueError("OfficeQA excludes UID0240")

    records = [row for row in exposure_registry.records if row.benchmark == benchmark]
    executed = {
        row.task_id
        for row in records
        if row.level.rank >= ExposureLevel.executed.rank
    }
    observed = {
        row.task_id for row in records if row.level == ExposureLevel.score_observed
    }
    screening_ids = {
        task.task_id
        for task in (
            list(clean_split.train)
            + list(clean_split.validation)
            + list(clean_split.clean_test)
        )
    }
    stratum = _domain_stratum(benchmark)

    confirmation_excluded = set(screening_ids) | executed
    confirmation_train = select_by_strata(
        source_pools["train"],
        count=counts.train,
        benchmark=benchmark,
        role="confirmation_train",
        candidate_index=0,
        stratum=stratum,
        excluded_ids=confirmation_excluded,
    )
    confirmation_excluded.update(task.task_id for task in confirmation_train)
    confirmation_validation = select_by_strata(
        source_pools["validation"],
        count=counts.validation,
        benchmark=benchmark,
        role="confirmation_validation",
        candidate_index=0,
        stratum=stratum,
        excluded_ids=confirmation_excluded,
    )
    confirmation_excluded.update(task.task_id for task in confirmation_validation)
    confirmation_test = select_by_strata(
        source_pools["test"],
        count=counts.test,
        benchmark=benchmark,
        role="confirmation_test",
        candidate_index=0,
        stratum=stratum,
        excluded_ids=confirmation_excluded,
    )
    confirmation_roles = {
        "train": confirmation_train,
        "validation": confirmation_validation,
        "confirmation_test": confirmation_test,
    }
    confirmation = ConfirmationSplit(
        benchmark=benchmark,
        domain=clean_split.domain,
        source_hash=_source_hash(confirmation_roles),
        selection_hash=canonical_hash(_ordered_ids(confirmation_roles)),
        metadata={
            "qualification_version": "noise-screen-v1",
            "selection_version": "noise-screen-v1",
            "reserved_before_screening": True,
            "static_audit": _static_audit(
                benchmark=benchmark,
                train=confirmation_train,
                validation=confirmation_validation,
                test=confirmation_test,
                require_recorded_headroom=False,
            ),
        },
        **confirmation_roles,
    )
    confirmation_ids = {
        task.task_id
        for tasks in confirmation_roles.values()
        for task in tasks
    }

    screening_test = select_by_strata(
        source_pools["test"],
        count=counts.test,
        benchmark=benchmark,
        role="screening_test",
        candidate_index=1,
        stratum=stratum,
        excluded_ids=screening_ids | confirmation_ids | observed,
    )
    fixed_ids = screening_ids | confirmation_ids | {
        task.task_id for task in screening_test
    }
    candidates = [
        _candidate(
            clean_split=clean_split,
            candidate_index=1,
            train=clean_split.train,
            screening_test=screening_test,
        )
    ]
    candidate_train_excluded = set(fixed_ids)
    for candidate_index in (2, 3):
        train = select_by_strata(
            source_pools["train"],
            count=counts.train,
            benchmark=benchmark,
            role="train",
            candidate_index=candidate_index,
            stratum=stratum,
            excluded_ids=candidate_train_excluded,
        )
        candidate_train_excluded.update(task.task_id for task in train)
        candidates.append(
            _candidate(
                clean_split=clean_split,
                candidate_index=candidate_index,
                train=train,
                screening_test=screening_test,
            )
        )
    return SelectionCandidateBundle(
        benchmark=benchmark,
        candidates=candidates,
        confirmation=confirmation,
        confirmation_seal=_seal(confirmation, exposure_registry),
    )


def _validate_skilllearn_family_split(
    family: str,
    split: CleanEvolutionSplitManifest,
    *,
    official_tasks_root: Path,
) -> None:
    if split.benchmark != "skilllearnbench" or split.domain != "skill_learning":
        raise ValueError(f"invalid SkillLearn identity for family {family}")
    family_root = official_tasks_root / family
    if not family_root.is_dir():
        raise ValueError(f"SkillLearn {family} official inventory is missing")
    numbered: list[tuple[int, str]] = []
    canonical_ids: set[str] = set()
    for path in family_root.iterdir():
        if not path.is_dir():
            continue
        match = re.fullmatch(rf"{re.escape(family)}-(\d+)", path.name)
        if match is None:
            raise ValueError(
                f"SkillLearn {family} official inventory has extra entry {path.name}"
            )
        number = int(match.group(1))
        canonical_id = f"{family}-{number}"
        if canonical_id in canonical_ids:
            raise ValueError(
                f"SkillLearn {family} has duplicate official inventory ID "
                f"{canonical_id}"
            )
        canonical_ids.add(canonical_id)
        numbered.append((number, canonical_id))
    numbered.sort()
    official_ids = [task_id for _, task_id in numbered]
    expected_inventory = [
        f"{family}-{index}" for index in range(1, len(official_ids) + 1)
    ]
    if official_ids != expected_inventory or len(official_ids) < 4:
        raise ValueError(f"SkillLearn {family} official inventory is not contiguous")

    expected_train = official_ids[:2]
    expected_validation = official_ids[2:3]
    expected_test = official_ids[3:]
    if [task.task_id for task in split.train] != expected_train:
        raise ValueError(f"SkillLearn {family} must use instances 1-2 for train")
    if [task.task_id for task in split.validation] != expected_validation:
        raise ValueError(f"SkillLearn {family} must use instance 3 for validation")
    if [task.task_id for task in split.clean_test] != expected_test:
        raise ValueError(
            f"SkillLearn {family} test must match official inventory remainder"
        )


def _skilllearn_task_structure_is_valid(
    task: TaskManifest,
    *,
    family: str,
    official_tasks_root: Path,
) -> bool:
    instance = official_tasks_root / family / task.task_id
    portable_path = f"rsebench-methods://skilllearnbench/tasks/{family}/{task.task_id}"
    if (
        task.metadata.get("task_family") != family
        or str(task.artifact_path) != portable_path
        or task.metadata.get("official_instance_path") != portable_path
        or task.verifier != "skilllearn_hidden_test_v1"
        or not instance.is_dir()
    ):
        return False
    instruction = instance / "instruction.md"
    task_config = instance / "task.toml"
    environment = instance / "environment"
    if not instruction.is_file() or not task_config.is_file() or not environment.is_dir():
        return False
    if instruction.read_text(encoding="utf-8") != task.prompt:
        return False
    try:
        config = tomllib.loads(task_config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    if not isinstance(config.get("verifier"), dict):
        return False
    return any(
        path.is_file() and path.name != "Dockerfile"
        for path in environment.rglob("*")
    )


def _skilllearn_n2_target_is_valid(
    task: TaskManifest,
    *,
    family: str,
    official_tasks_root: Path,
) -> bool:
    suffixes = _SKILLLEARN_N2_TARGET_SUFFIXES.get(family, frozenset())
    environment = official_tasks_root / family / task.task_id / "environment"
    return bool(suffixes) and any(
        path.is_file()
        and path.name != "Dockerfile"
        and path.suffix.casefold() in suffixes
        for path in environment.rglob("*")
    )


def _skilllearn_noise_applicability(
    screening_splits: Mapping[str, CleanEvolutionSplitManifest],
    *,
    official_tasks_root: Path,
) -> dict[str, dict[str, float | int | str | None]]:
    acquisition = [
        (family, task)
        for family in SCREENING_SKILLLEARN_FAMILIES
        for task in screening_splits[family].train
    ]
    denominator = len(SCREENING_SKILLLEARN_FAMILIES) * 2
    if len(acquisition) != denominator:
        raise ValueError("SkillLearn applicability denominator must be eight")
    predicates = {
        "N1": [
            _skilllearn_task_structure_is_valid(
                task,
                family=family,
                official_tasks_root=official_tasks_root,
            )
            and family in _SKILLLEARN_N1_TARGETS
            for family, task in acquisition
        ],
        "N2": [
            _skilllearn_task_structure_is_valid(
                task,
                family=family,
                official_tasks_root=official_tasks_root,
            )
            and _skilllearn_n2_target_is_valid(
                task,
                family=family,
                official_tasks_root=official_tasks_root,
            )
            for family, task in acquisition
        ],
    }
    statuses: dict[str, dict[str, float | int | str | None]] = {}
    for stage, results in predicates.items():
        applicable = sum(results)
        coverage = applicable / denominator
        statuses[stage] = {
            "applicable": applicable,
            "coverage": coverage,
            "denominator": denominator,
            "status": "pass" if applicable == denominator else "fail",
        }
    statuses["N3"] = {"coverage": None, "status": "pending"}
    statuses["N4"] = {"coverage": None, "status": "pending"}
    return statuses


def build_skilllearn_selection_candidates(
    *,
    screening_splits: Mapping[str, CleanEvolutionSplitManifest],
    confirmation_splits: Mapping[str, CleanEvolutionSplitManifest],
    exposure_registry: ExposureRegistry,
    official_tasks_root: str | Path = DEFAULT_SKILLLEARN_TASKS_ROOT,
) -> SelectionCandidateBundle:
    """Build the one preregistered fixed-family SkillLearn candidate."""

    if set(screening_splits) != set(SCREENING_SKILLLEARN_FAMILIES):
        raise ValueError("SkillLearn screening families differ from preregistration")
    if set(confirmation_splits) != set(CONFIRMATION_SKILLLEARN_FAMILIES):
        raise ValueError("SkillLearn confirmation families differ from preregistration")
    tasks_root = Path(official_tasks_root)
    all_splits = {**screening_splits, **confirmation_splits}
    for family, split in all_splits.items():
        _validate_skilllearn_family_split(
            family,
            split,
            official_tasks_root=tasks_root,
        )
        ordinary_tasks = [*split.validation, *split.clean_test]
        if family in CONFIRMATION_SKILLLEARN_FAMILIES:
            ordinary_tasks = [*split.train, *ordinary_tasks]
        if not all(
            _skilllearn_task_structure_is_valid(
                task,
                family=family,
                official_tasks_root=tasks_root,
            )
            for task in ordinary_tasks
        ):
            raise ValueError(f"SkillLearn {family} official task structure is invalid")

    screening_order = [screening_splits[name] for name in SCREENING_SKILLLEARN_FAMILIES]
    confirmation_order = [
        confirmation_splits[name] for name in CONFIRMATION_SKILLLEARN_FAMILIES
    ]
    reference = screening_order[0]
    for split in screening_order[1:]:
        if split.seed != reference.seed:
            raise ValueError("SkillLearn screening source seeds differ")
        for key in ("runtime", "baseline", "feedback_mode"):
            if split.metadata.get(key) != reference.metadata.get(key):
                raise ValueError(f"SkillLearn screening {key} differs")
    screening_roles = {
        "train": [task for split in screening_order for task in split.train],
        "validation": [task for split in screening_order for task in split.validation],
        "qualification_test": [
            task for split in screening_order for task in split.clean_test
        ],
        "screening_test": [
            task for split in screening_order for task in split.clean_test
        ],
    }
    # The finite-instance exception means qualification and screening are the same
    # family tail semantically, but StableSplitCandidate requires disjoint roles.
    # Qualification is therefore empty: these family tails are screening evidence.
    screening_roles["qualification_test"] = []
    applicability = _skilllearn_noise_applicability(
        screening_splits,
        official_tasks_root=tasks_root,
    )
    if any(applicability[stage]["status"] != "pass" for stage in ("N1", "N2")):
        raise ValueError("SkillLearn N1/N2 static applicability must be 100%")
    candidate = StableSplitCandidate(
        benchmark="skilllearnbench",
        domain="skill_learning",
        candidate_index=1,
        source_hash=_source_hash(screening_roles),
        selection_hash=canonical_hash(_ordered_ids(screening_roles)),
        metadata={
            "qualification_version": "noise-screen-v1",
            "selection_version": "noise-screen-v1",
            "source_seed": reference.seed,
            "runtime": reference.metadata.get("runtime"),
            "baseline": reference.metadata.get("baseline"),
            "feedback_mode": reference.metadata.get("feedback_mode"),
            "families": list(SCREENING_SKILLLEARN_FAMILIES),
            "development_screening_exception": True,
            "static_audit": {
                "noise_applicability": applicability,
                "family_allocations": {
                    family: {
                        "train": [task.task_id for task in screening_splits[family].train],
                        "validation": [
                            task.task_id for task in screening_splits[family].validation
                        ],
                        "screening_test": [
                            task.task_id for task in screening_splits[family].clean_test
                        ],
                    }
                    for family in SCREENING_SKILLLEARN_FAMILIES
                },
            },
        },
        **screening_roles,
    )

    confirmation_roles = {
        "train": [task for split in confirmation_order for task in split.train],
        "validation": [task for split in confirmation_order for task in split.validation],
        "confirmation_test": [
            task for split in confirmation_order for task in split.clean_test
        ],
    }
    executed = {
        row.task_id
        for row in exposure_registry.records
        if row.benchmark == "skilllearnbench"
        and row.level.rank >= ExposureLevel.executed.rank
    }
    confirmation_ids = {
        task.task_id for tasks in confirmation_roles.values() for task in tasks
    }
    if overlap := executed & confirmation_ids:
        raise ValueError(
            f"SkillLearn confirmation contains historically executed tasks: {sorted(overlap)}"
        )
    confirmation = ConfirmationSplit(
        benchmark="skilllearnbench",
        domain="skill_learning",
        source_hash=_source_hash(confirmation_roles),
        selection_hash=canonical_hash(_ordered_ids(confirmation_roles)),
        metadata={
            "qualification_version": "noise-screen-v1",
            "selection_version": "noise-screen-v1",
            "families": list(CONFIRMATION_SKILLLEARN_FAMILIES),
            "reserved_before_screening": True,
        },
        **confirmation_roles,
    )
    return SelectionCandidateBundle(
        benchmark="skilllearnbench",
        candidates=[candidate],
        confirmation=confirmation,
        confirmation_seal=_seal(confirmation, exposure_registry),
    )


__all__ = [
    "CONFIRMATION_SKILLLEARN_FAMILIES",
    "SCREENING_SKILLLEARN_FAMILIES",
    "SPREADSHEET_KEYWORD_MAP_VERSION",
    "SPREADSHEET_OPERATION_KEYWORDS",
    "SelectionCandidateBundle",
    "SelectionCounts",
    "build_selection_candidates",
    "build_skilllearn_selection_candidates",
    "officeqa_stratum",
    "round_robin_exact",
    "select_by_strata",
    "skilllearn_stratum",
    "spreadsheet_operation_category",
    "webshop_stratum",
]
