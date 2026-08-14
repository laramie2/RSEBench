import json
from pathlib import Path

import pytest

from scripts.aggregate_clean_qualification import build_aggregate


METHOD_SEEDS = (20260813, 20260814, 20260815)
BENCHMARKS = (
    "spreadsheetbench_verified",
    "officeqa_full",
    "webshop",
)
FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
    "github-repo-analytics",
    "financial-analysis",
    "stock-data-visualization",
    "enterprise-information-search",
)


def _write_result(
    run_root: Path,
    *,
    benchmark: str,
    method_seed: int,
    passed: bool,
    family: str | None = None,
    run_id: str = "run-1",
) -> None:
    prefix = run_root / benchmark
    if family is not None:
        prefix /= family
    run_dir = prefix / str(method_seed) / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "benchmark": benchmark,
                "family": family,
                "method_seed": method_seed,
                "qualification": {
                    "passed": passed,
                    "accepted_update_count": 1 if passed else 0,
                    "clean_gain": 0.25 if passed else 0.0,
                    "failure_reasons": [] if passed else ["no_accepted_update"],
                },
                "metadata": {"config_version": "clean-qualification-v1"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_aggregate_requires_two_of_three_runs_and_four_of_eight_families(
    tmp_path: Path,
) -> None:
    for benchmark in BENCHMARKS:
        for index, method_seed in enumerate(METHOD_SEEDS):
            _write_result(
                tmp_path,
                benchmark=benchmark,
                method_seed=method_seed,
                passed=index < 2,
            )
    for family_index, family in enumerate(FAMILIES):
        for seed_index, method_seed in enumerate(METHOD_SEEDS):
            _write_result(
                tmp_path,
                benchmark="skilllearnbench",
                family=family,
                method_seed=method_seed,
                passed=family_index < 4 and seed_index < 2,
            )

    payload = build_aggregate(tmp_path)

    assert payload["benchmarks"]["spreadsheetbench_verified"]["passed_runs"] == 2
    assert payload["benchmarks"]["spreadsheetbench_verified"]["qualified"] is True
    assert (
        payload["skilllearn"]["families"]["offer-letter-generator"]["qualified"] is True
    )
    assert payload["skilllearn"]["qualified_family_count"] == 4
    assert payload["skilllearn"]["qualified"] is True
    assert payload["all_benchmarks_qualified"] is True
    assert payload["token_usage"]["event_count"] == 0


def test_missing_seed_remains_in_fixed_denominator(tmp_path: Path) -> None:
    _write_result(
        tmp_path,
        benchmark="spreadsheetbench_verified",
        method_seed=METHOD_SEEDS[0],
        passed=True,
    )
    _write_result(
        tmp_path,
        benchmark="spreadsheetbench_verified",
        method_seed=METHOD_SEEDS[1],
        passed=False,
    )

    payload = build_aggregate(tmp_path)
    spreadsheet = payload["benchmarks"]["spreadsheetbench_verified"]

    assert spreadsheet["total_runs"] == 3
    assert spreadsheet["passed_runs"] == 1
    assert spreadsheet["missing_runs"] == 1
    assert spreadsheet["runs"][2]["status"] == "missing"
    assert spreadsheet["qualified"] is False


def test_duplicate_completed_result_for_one_seed_is_rejected(tmp_path: Path) -> None:
    for run_id in ("run-1", "run-2"):
        _write_result(
            tmp_path,
            benchmark="webshop",
            method_seed=METHOD_SEEDS[0],
            passed=True,
            run_id=run_id,
        )

    with pytest.raises(ValueError, match="duplicate completed clean qualification"):
        build_aggregate(tmp_path)
