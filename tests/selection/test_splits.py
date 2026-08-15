from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.selection import ExposureLevel, ExposureRecord, ExposureRegistry
from rsebench.selection.splits import (
    SelectionCounts,
    build_selection_candidates,
    build_skilllearn_selection_candidates,
    officeqa_stratum,
    round_robin_exact,
    spreadsheet_operation_category,
    webshop_stratum,
)


HASH = "a" * 64
ROOT = Path(__file__).parents[2]


def task_ids(tasks: Sequence[TaskManifest]) -> list[str]:
    return [task.task_id for task in tasks]


def _task(
    benchmark: str,
    domain: str,
    task_id: str,
    *,
    prompt: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain=domain,
        prompt=prompt or f"Task {task_id}",
        gold_answers=["answer"] if domain == "document" else [],
        verifier=None if domain == "document" else f"{benchmark}_verifier_v1",
        source_hash=canonical_hash([benchmark, task_id]),
        metadata={
            "static_applicability": {"N1": True, "N2": True},
            **(metadata or {}),
        },
    )


def _pool(
    benchmark: str,
    domain: str,
    prefix: str,
    count: int,
) -> list[TaskManifest]:
    spreadsheet_prompts = (
        "lookup and join tables with xlookup",
        "calculate a total with sumifs formula",
        "clean text and convert a date",
        "create a pivot chart and format layout",
        "edit the workbook values",
    )
    tasks = []
    for index in range(count):
        metadata: dict[str, Any] = {}
        prompt = f"Task {prefix}-{index}"
        if benchmark == "spreadsheetbench_verified":
            prompt = spreadsheet_prompts[index % len(spreadsheet_prompts)]
        elif benchmark == "officeqa_full":
            metadata = {
                "difficulty": "hard" if index % 2 else "easy",
                "source_file_count": 2 if index % 3 else 1,
                "officeqa_stratum": f"difficulty={index % 2}|files={1 + index % 2}",
            }
            axes = (
                "What was reported during fiscal year 1992?",
                "What was the amount in millions of dollars?",
                "What did the Treasury entity report?",
                "What was the total combined amount?",
                "What value was reported?",
            )
            prompt = axes[index % len(axes)]
        elif benchmark == "webshop":
            metadata = {
                "query": f"query {prefix} {index}",
                "normalized_query": f"query {prefix} {index}",
                "target_asin": f"ASIN{prefix}{index}",
                "target_reachable": True,
                "option_count": index % 3,
                "constraint_count": 2 + index % 4,
                "retrieval_rank": index % 10,
            }
        tasks.append(
            _task(
                benchmark,
                domain,
                f"{prefix}-{index:03d}",
                prompt=prompt,
                metadata=metadata,
            )
        )
    return tasks


def _clean_split(
    benchmark: str,
    domain: str,
    *,
    train_count: int,
    validation_count: int,
    test_count: int,
) -> CleanEvolutionSplitManifest:
    train = _pool(benchmark, domain, "clean-train", train_count)
    validation = _pool(benchmark, domain, "clean-validation", validation_count)
    if benchmark == "webshop":
        validation = [
            task.model_copy(
                update={
                    "metadata": {
                        **task.metadata,
                        "seed_success": index < 2,
                    }
                }
            )
            for index, task in enumerate(validation)
        ]
    clean_test = _pool(benchmark, domain, "qualification", test_count)
    return CleanEvolutionSplitManifest(
        benchmark=benchmark,
        domain=domain,
        seed=20260813,
        source_hash=canonical_hash(
            [benchmark, task_ids(train), task_ids(validation), task_ids(clean_test)]
        ),
        train=train,
        validation=validation,
        clean_test=clean_test,
        metadata={"qualification_version": "clean-qualification-v2"},
    )


def _registry(
    benchmark: str,
    *,
    observed: Sequence[str] = (),
    executed: Sequence[str] = (),
) -> ExposureRegistry:
    records = [
        ExposureRecord(
            benchmark=benchmark,
            task_id=task_id,
            level=level,
            roles=["fixture"],
            sources=["fixture"],
        )
        for level, task_ids_for_level in (
            (ExposureLevel.score_observed, observed),
            (ExposureLevel.executed, executed),
        )
        for task_id in task_ids_for_level
    ]
    return ExposureRegistry(
        records=records,
        registry_hash=canonical_hash(
            [record.model_dump(mode="json") for record in records]
        ),
    )


def _bundle(
    benchmark: str,
    domain: str,
    counts: SelectionCounts,
):
    clean = _clean_split(
        benchmark,
        domain,
        train_count=counts.train,
        validation_count=counts.validation,
        test_count=counts.test,
    )
    pools = {
        "train": _pool(benchmark, domain, "source-train", counts.train * 6),
        "validation": _pool(
            benchmark,
            domain,
            "source-validation",
            counts.validation * 2,
        ),
        "test": _pool(benchmark, domain, "source-test", counts.test * 3),
    }
    observed = [pools["test"][0].task_id]
    executed = [pools["train"][0].task_id, pools["validation"][0].task_id]
    registry = _registry(benchmark, observed=observed, executed=executed)
    return (
        build_selection_candidates(
            clean_split=clean,
            source_pools=pools,
            exposure_registry=registry,
            counts=counts,
        ),
        registry,
    )


@pytest.mark.parametrize(
    ("benchmark", "domain", "counts"),
    [
        (
            "spreadsheetbench_verified",
            "spreadsheet",
            SelectionCounts(train=20, validation=10, test=30),
        ),
        (
            "officeqa_full",
            "document",
            SelectionCounts(train=12, validation=12, test=20),
        ),
        (
            "webshop",
            "interactive",
            SelectionCounts(train=5, validation=5, test=20),
        ),
    ],
)
def test_exact_counts_and_determinism(
    benchmark: str,
    domain: str,
    counts: SelectionCounts,
) -> None:
    first, _ = _bundle(benchmark, domain, counts)
    second, _ = _bundle(benchmark, domain, counts)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [
        (len(row.train), len(row.validation), len(row.screening_test))
        for row in first.candidates
    ] == [(counts.train, counts.validation, counts.test)] * 3
    assert (
        len(first.confirmation.train),
        len(first.confirmation.validation),
        len(first.confirmation.confirmation_test),
    ) == (counts.train, counts.validation, counts.test)


def test_candidate_two_changes_train_only() -> None:
    candidate_bundle, _ = _bundle(
        "officeqa_full",
        "document",
        SelectionCounts(train=12, validation=12, test=20),
    )
    first, second = candidate_bundle.candidates[:2]

    assert task_ids(first.validation) == task_ids(second.validation)
    assert task_ids(first.qualification_test) == task_ids(
        second.qualification_test
    )
    assert task_ids(first.screening_test) == task_ids(second.screening_test)
    assert task_ids(first.train) != task_ids(second.train)


def test_confirmation_is_reserved_before_candidates() -> None:
    candidate_bundle, _ = _bundle(
        "spreadsheetbench_verified",
        "spreadsheet",
        SelectionCounts(train=20, validation=10, test=30),
    )

    assert not set(candidate_bundle.screening_all_ids) & set(
        candidate_bundle.confirmation_all_ids
    )
    assert candidate_bundle.confirmation_seal.created_before_screening is True


def test_new_test_excludes_observed_tasks() -> None:
    candidate_bundle, exposure_registry = _bundle(
        "webshop",
        "interactive",
        SelectionCounts(train=5, validation=5, test=20),
    )
    observed = {
        row.task_id
        for row in exposure_registry.records
        if row.level == ExposureLevel.score_observed
    }

    assert not set(candidate_bundle.screening_test_ids) & observed


def test_confirmation_excludes_historically_executed_tasks() -> None:
    candidate_bundle, exposure_registry = _bundle(
        "officeqa_full",
        "document",
        SelectionCounts(train=12, validation=12, test=20),
    )
    executed = {
        row.task_id
        for row in exposure_registry.records
        if row.level.rank >= ExposureLevel.executed.rank
    }

    assert not set(candidate_bundle.confirmation_all_ids) & executed


def test_round_robin_exact_fails_closed_on_insufficient_pool() -> None:
    rows = _pool("officeqa_full", "document", "tiny", 2)

    with pytest.raises(ValueError, match="insufficient eligible pool: requested 3"):
        round_robin_exact({"easy": rows}, count=3)


def test_exact_domain_strata_are_stable() -> None:
    spreadsheet = _pool(
        "spreadsheetbench_verified", "spreadsheet", "sheet", 5
    )
    office = _pool("officeqa_full", "document", "office", 5)
    webshop = _pool("webshop", "interactive", "shop", 1)[0]

    assert [spreadsheet_operation_category(task) for task in spreadsheet] == [
        "lookup_join",
        "aggregation_formula",
        "text_date_cleaning",
        "layout_chart_pivot",
        "other",
    ]
    assert {officeqa_stratum(task).rsplit("|axis=", 1)[1] for task in office} == {
        "period",
        "unit",
        "entity",
        "aggregation",
        "other",
    }
    assert webshop_stratum(webshop) == "options=0|constraints=2-3|rank=1-3"


def test_static_audits_preserve_batches_coverage_and_pending_semantics() -> None:
    spreadsheet, _ = _bundle(
        "spreadsheetbench_verified",
        "spreadsheet",
        SelectionCounts(train=20, validation=10, test=30),
    )
    office, _ = _bundle(
        "officeqa_full",
        "document",
        SelectionCounts(train=12, validation=12, test=20),
    )
    webshop, _ = _bundle(
        "webshop",
        "interactive",
        SelectionCounts(train=5, validation=5, test=20),
    )

    sheet_audit = spreadsheet.candidates[0].metadata["static_audit"]
    assert sheet_audit["train_batch_sizes"] == [7, 7, 6]
    assert len(sheet_audit["operation_categories"]) >= 4
    office_audit = office.candidates[0].metadata["static_audit"]
    assert office_audit["train_batch_sizes"] == [4, 4, 4]
    assert "UID0240" not in office.screening_all_ids
    assert len(office_audit["difficulty_coverage"]) == 2
    assert len(office_audit["source_file_count_coverage"]) >= 2
    assert len(office_audit["question_axis_coverage"]) == 5
    webshop_audit = webshop.candidates[0].metadata["static_audit"]
    assert webshop_audit["unique_normalized_queries"] is True
    assert webshop_audit["reachable_target_asins"] is True
    assert webshop_audit["validation_headroom"] == {"successes": 2, "total": 5}
    for bundle in (spreadsheet, office, webshop):
        applicability = bundle.candidates[0].metadata["static_audit"][
            "noise_applicability"
        ]
        assert applicability["N1"] == {"coverage": 1.0, "status": "pass"}
        assert applicability["N2"] == {"coverage": 1.0, "status": "pass"}
        assert applicability["N3"] == {"coverage": None, "status": "pending"}
        assert applicability["N4"] == {"coverage": None, "status": "pending"}


def test_webshop_fails_closed_when_recorded_headroom_is_not_two_of_five() -> None:
    counts = SelectionCounts(train=5, validation=5, test=20)
    clean = _clean_split(
        "webshop",
        "interactive",
        train_count=5,
        validation_count=5,
        test_count=20,
    )
    bad_validation = [
        task.model_copy(
            update={"metadata": {**task.metadata, "seed_success": False}}
        )
        for task in clean.validation
    ]
    clean = clean.model_copy(update={"validation": bad_validation})
    pools = {
        "train": _pool("webshop", "interactive", "source-train", 30),
        "validation": _pool("webshop", "interactive", "source-validation", 10),
        "test": _pool("webshop", "interactive", "source-test", 60),
    }

    with pytest.raises(ValueError, match="exactly 2/5 validation headroom"):
        build_selection_candidates(
            clean_split=clean,
            source_pools=pools,
            exposure_registry=_registry("webshop"),
            counts=counts,
        )


def _load_clean(path: Path) -> CleanEvolutionSplitManifest:
    return CleanEvolutionSplitManifest.model_validate_json(path.read_text())


def test_skilllearn_uses_fixed_families_and_instance_allocation() -> None:
    root = ROOT / "benchmark/validation/clean_qualification_v2/skilllearnbench"
    screening_names = (
        "organize-messy-files",
        "offer-letter-generator",
        "schedule-planning",
        "dependency-vulnerability-check",
    )
    confirmation_names = (
        "github-repo-analytics",
        "financial-analysis",
        "stock-data-visualization",
        "enterprise-information-search",
    )
    screening = {name: _load_clean(root / f"{name}.json") for name in screening_names}
    confirmation = {
        name: _load_clean(root / f"{name}.json") for name in confirmation_names
    }

    bundle = build_skilllearn_selection_candidates(
        screening_splits=screening,
        confirmation_splits=confirmation,
        exposure_registry=_registry("skilllearnbench"),
    )

    assert bundle.candidates[0].metadata["families"] == list(screening_names)
    assert bundle.confirmation.metadata["families"] == list(confirmation_names)
    assert len(bundle.candidates) == 1
    for family, split in {**screening, **confirmation}.items():
        assert task_ids(split.train) == [f"{family}-1", f"{family}-2"]
        assert task_ids(split.validation) == [f"{family}-3"]
        assert task_ids(split.clean_test) == [
            f"{family}-{index}" for index in range(4, 4 + len(split.clean_test))
        ]
    applicability = bundle.candidates[0].metadata["static_audit"][
        "noise_applicability"
    ]
    assert applicability["N1"]["status"] == "pass"
    assert applicability["N2"]["status"] == "pass"
    assert applicability["N3"]["status"] == "pending"
    assert applicability["N4"]["status"] == "pending"


def test_selection_and_seal_hashes_cover_ordered_task_ids() -> None:
    bundle, _ = _bundle(
        "spreadsheetbench_verified",
        "spreadsheet",
        SelectionCounts(train=20, validation=10, test=30),
    )
    candidate = bundle.candidates[0]
    expected_ids = {
        "train": task_ids(candidate.train),
        "validation": task_ids(candidate.validation),
        "qualification_test": task_ids(candidate.qualification_test),
        "screening_test": task_ids(candidate.screening_test),
    }

    assert candidate.selection_hash == canonical_hash(expected_ids)
    assert bundle.confirmation_seal.task_ids == {
        "train": task_ids(bundle.confirmation.train),
        "validation": task_ids(bundle.confirmation.validation),
        "confirmation_test": task_ids(bundle.confirmation.confirmation_test),
    }
    assert json.loads(bundle.model_dump_json())["candidates"][0][
        "selection_hash"
    ] == candidate.selection_hash
