from __future__ import annotations

import hashlib
from pathlib import Path

from rsebench.datasets import BenchmarkDataset, load_dataset_release
from scripts.freeze_validation_v1 import freeze_validation_v1


ROOT = Path(__file__).resolve().parents[2]


def _load_all():
    return tuple(load_dataset_release(path) for path in freeze_validation_v1(ROOT))


def test_freeze_creates_exact_four_domain_releases() -> None:
    releases = _load_all()

    assert tuple((release.domain, release.benchmark) for release in releases) == (
        ("spreadsheet", "spreadsheetbench_verified"),
        ("document", "officeqa_full"),
        ("interactive", "webshop"),
        ("skill", "skillflow_tasks"),
    )
    assert {release.release_id for release in releases} == {
        "spreadsheetbench-verified-validation-v1",
        "officeqa-full-validation-v1",
        "webshop-validation-v1",
        "skillflow-tasks-validation-v1",
    }


def test_split_release_counts_are_frozen() -> None:
    expected = {
        "spreadsheetbench_verified": (20, 10, 30),
        "officeqa_full": (12, 12, 20),
        "webshop": (5, 5, 20),
    }

    for release in _load_all():
        if release.benchmark in expected:
            assert tuple(
                len(release.partitions[name])
                for name in ("train", "validation", "test")
            ) == expected[release.benchmark]


def test_skillflow_release_has_exact_three_six_task_groups() -> None:
    releases = _load_all()
    release = next(row for row in releases if row.benchmark == "skillflow_tasks")
    dataset = BenchmarkDataset(release)

    assert dataset.group_names() == (
        "HWPX-Document-Automation",
        "Distribution-Center-Auditing",
        "Embedded-Data-Repair",
    )
    assert tuple(len(dataset.group(name)) for name in dataset.group_names()) == (6, 6, 6)
    assert tuple(task.task_id for task in dataset.group("HWPX-Document-Automation")) == (
        "hwpx-supplier-contact-sheet",
        "hwpx-event-announcement",
        "hwpx-clinic-intake-summary",
        "hwpx-project-proposal",
        "hwpx-training-feedback",
        "hwpx-safety-audit-brief",
    )
    assert tuple(
        task.task_id for task in dataset.group("Distribution-Center-Auditing")
    ) == (
        "harbor_receiving_exception_audit",
        "harbor_trailer_detention_audit",
        "harbor_promo_register_audit",
        "harbor_service_queue_sla_audit",
        "harbor_timesheet_policy_audit",
        "harbor_returns_disposition_audit",
    )
    assert tuple(task.task_id for task in dataset.group("Embedded-Data-Repair")) == (
        "fx-spot-matrix-refresh",
        "fx-cross-rate-inverse-fix",
        "warehouse-slot-factor-refresh",
        "supplier-pack-matrix-refresh",
        "catalyst-balance-matrix-sync",
        "buffer-dilution-matrix-repair",
    )


def test_freeze_is_idempotent_and_path_independent() -> None:
    first = freeze_validation_v1(ROOT)
    first_hashes = {
        path.relative_to(ROOT): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first
    }
    second = freeze_validation_v1(ROOT)
    second_hashes = {
        path.relative_to(ROOT): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second
    }

    assert second_hashes == first_hashes
    for path in second:
        assert str(ROOT) not in path.read_text(encoding="utf-8")
