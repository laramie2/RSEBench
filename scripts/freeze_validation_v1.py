#!/usr/bin/env python3
"""Freeze the approved provider-free validation-v1 benchmark selections."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from rsebench.contracts import TaskManifest
from rsebench.datasets import (
    DatasetRelease,
    EvidenceReference,
    ResourceIdentity,
    build_dataset_release,
)


_SPLIT_SOURCES: tuple[dict[str, str], ...] = (
    {
        "domain": "spreadsheet",
        "benchmark": "spreadsheetbench_verified",
        "release_id": "spreadsheetbench-verified-validation-v1",
        "source": "benchmark/validation/clean_qualification_v2/spreadsheetbench_verified.json",
        "file_sha256": "b27721f6c317e6af26acb11311276e42987ca24a4872b89722a245a782ad1838",
        "source_hash": "4e6d076bbcfa1e2793233361b1782f88a1e955104480117502af88ffa31b1174",
        "loader": "rsebench.task_manifest.v1",
        "verifier": "spreadsheetbench_cell_range_v1",
    },
    {
        "domain": "document",
        "benchmark": "officeqa_full",
        "release_id": "officeqa-full-validation-v1",
        "source": "benchmark/validation/clean_qualification_v2/officeqa_full.json",
        "file_sha256": "8c715c2917c4db111f2bddeb80b6b7937c426276fe72f61e07166981363a85d6",
        "source_hash": "b942f7f8f947daff9d48dfc3bf8206cfb2010afdd3c0a74af2346e123d69cd16",
        "loader": "rsebench.task_manifest.v1",
        "verifier": "officeqa_released_numeric_v1",
    },
    {
        "domain": "interactive",
        "benchmark": "webshop",
        "release_id": "webshop-validation-v1",
        "source": "benchmark/validation/clean_qualification_v2/webshop.json",
        "file_sha256": "56f6a68e348c9006882f3b6ba9b77add161f01b863737993a4bc5e474390bbf8",
        "source_hash": "0a2bd44ca5f26d5f8cd28c6b0d883c02b0fc01565173f21f907f2b5200d95f55",
        "loader": "rsebench.task_manifest.v1",
        "verifier": "webshop_official_reward_v1",
    },
)

_SKILLFLOW_SOURCES = (
    {
        "source": "benchmark/validation/skillflow_clean_qualification_v1/noise_validation_selection.json",
        "file_sha256": "1d7caec1bd273a742e7c62467c9b694b0c7b8cbf17bb61fab2e7723fa2a2b0d7",
    },
    {
        "source": "benchmark/validation/skillflow_clean_qualification_v1/second_family_candidates_batch2.json",
        "file_sha256": "205fea257c57537e8f7ea54f3fcc97530106d6a0b43202a717f17504c2476016",
    },
)

_SKILLFLOW_GROUPS: dict[str, tuple[str, ...]] = {
    "HWPX-Document-Automation": (
        "hwpx-supplier-contact-sheet",
        "hwpx-event-announcement",
        "hwpx-clinic-intake-summary",
        "hwpx-project-proposal",
        "hwpx-training-feedback",
        "hwpx-safety-audit-brief",
    ),
    "Distribution-Center-Auditing": (
        "harbor_receiving_exception_audit",
        "harbor_trailer_detention_audit",
        "harbor_promo_register_audit",
        "harbor_service_queue_sla_audit",
        "harbor_timesheet_policy_audit",
        "harbor_returns_disposition_audit",
    ),
    "Embedded-Data-Repair": (
        "fx-spot-matrix-refresh",
        "fx-cross-rate-inverse-fix",
        "warehouse-slot-factor-refresh",
        "supplier-pack-matrix-refresh",
        "catalyst-balance-matrix-sync",
        "buffer-dilution-matrix-repair",
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_verified_json(root: Path, relative: str, expected_sha256: str) -> Any:
    path = root / relative
    actual = _sha256(path)
    if actual != expected_sha256:
        raise ValueError(
            f"approved source hash differs for {relative}: {actual} != {expected_sha256}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _source_uri(relative: str) -> str:
    return f"rsebench-project://{relative}"


def _split_release(root: Path, spec: Mapping[str, str]) -> DatasetRelease:
    payload = _load_verified_json(root, spec["source"], spec["file_sha256"])
    if payload["source_hash"] != spec["source_hash"]:
        raise ValueError(f"source_hash differs in {spec['source']}")
    if payload["benchmark"] != spec["benchmark"] or payload["domain"] != spec["domain"]:
        raise ValueError(f"benchmark identity differs in {spec['source']}")

    partitions: dict[str, tuple[str, ...]] = {}
    tasks: dict[str, TaskManifest] = {}
    for target_name, source_name in (
        ("train", "train"),
        ("validation", "validation"),
        ("test", "clean_test"),
    ):
        members: list[str] = []
        for raw_task in payload[source_name]:
            task = TaskManifest.model_validate(raw_task)
            if task.task_id in tasks:
                raise ValueError(
                    f"task occurs in multiple partitions: {task.task_id}"
                )
            tasks[task.task_id] = task
            members.append(task.task_id)
        partitions[target_name] = tuple(members)

    source = ResourceIdentity(
        uri=_source_uri(spec["source"]),
        sha256=spec["file_sha256"],
        kind="approved-selection-manifest",
    )
    provenance = EvidenceReference(
        uri=_source_uri(spec["source"]),
        sha256=spec["source_hash"],
        kind="selection-source-hash",
    )
    return build_dataset_release(
        release_id=spec["release_id"],
        domain=spec["domain"],
        benchmark=spec["benchmark"],
        benchmark_version="validation-v1",
        loader=spec["loader"],
        verifier=spec["verifier"],
        tasks=tasks,
        partitions=partitions,
        source_resources=(source,),
        provenance=(provenance,),
        metadata={
            "freeze_policy": "inherit-approved-order-without-resampling",
            "seed": payload["seed"],
        },
    )


def _skillflow_rows(
    selection: Mapping[str, Any], candidates: Mapping[str, Any]
) -> dict[str, Sequence[Mapping[str, Any]]]:
    rows: dict[str, Sequence[Mapping[str, Any]]] = {
        selection["family"]: selection["tasks"]
    }
    rows.update(
        {candidate["family"]: candidate["tasks"] for candidate in candidates["candidates"]}
    )
    return rows


def _skillflow_release(root: Path) -> DatasetRelease:
    selection_spec, candidates_spec = _SKILLFLOW_SOURCES
    selection = _load_verified_json(
        root, selection_spec["source"], selection_spec["file_sha256"]
    )
    candidates = _load_verified_json(
        root, candidates_spec["source"], candidates_spec["file_sha256"]
    )
    rows_by_family = _skillflow_rows(selection, candidates)
    tasks: dict[str, TaskManifest] = {}

    for family, approved_ids in _SKILLFLOW_GROUPS.items():
        source_rows = tuple(rows_by_family[family])
        source_ids = tuple(str(row["task_id"]) for row in source_rows[:6])
        if source_ids != approved_ids:
            raise ValueError(f"approved SkillFlow order differs for {family}")
        for row in source_rows[:6]:
            task_id = str(row["task_id"])
            relative_path = str(row["relative_path"])
            tasks[task_id] = TaskManifest(
                task_id=task_id,
                benchmark="skillflow_tasks",
                domain="skill",
                prompt=f"Execute the frozen SkillFlow task {task_id}.",
                source_hash=str(row["task_hash"]),
                artifact_path=(
                    "rsebench-data://raw/skillflow_tasks/test_tasks/"
                    f"{relative_path}"
                ),
                verifier="skillflow_harbor_v1",
                metadata={
                    "family": family,
                    "order": int(row["order"]),
                    "relative_path": relative_path,
                },
            )

    resources = tuple(
        ResourceIdentity(
            uri=_source_uri(spec["source"]),
            sha256=spec["file_sha256"],
            kind="approved-selection-manifest",
        )
        for spec in _SKILLFLOW_SOURCES
    )
    return build_dataset_release(
        release_id="skillflow-tasks-validation-v1",
        domain="skill",
        benchmark="skillflow_tasks",
        benchmark_version=str(selection["upstream_revision"]),
        loader="skillflow.harbor_task.v1",
        verifier="skillflow_harbor_v1",
        tasks=tasks,
        groups=_SKILLFLOW_GROUPS,
        source_resources=resources,
        provenance=tuple(
            EvidenceReference(
                uri=resource.uri,
                sha256=resource.sha256,
                kind="clean-screening-evidence",
            )
            for resource in resources
        ),
        metadata={
            "family_execution": "serial-in-family-reset-between-families",
            "selection_purpose": "noise-mechanism-validation",
            "selection_warning": (
                "clean efficacy is not an unbiased estimate of full-benchmark efficacy"
            ),
        },
    )


def _release_path(root: Path, release: DatasetRelease) -> Path:
    return (
        root
        / "benchmark"
        / "datasets"
        / release.domain
        / release.benchmark
        / "releases"
        / "validation-v1"
        / "manifest.json"
    )


def _write_immutable(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RuntimeError(f"refusing to overwrite different frozen content: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_benchmark_metadata(root: Path, release: DatasetRelease) -> None:
    path = _release_path(root, release).parents[2] / "benchmark.yaml"
    payload = {
        "schema_version": "rsebench.benchmark.v1",
        "benchmark": release.benchmark,
        "domain": release.domain,
        "default_release": "validation-v1",
        "releases": {
            "validation-v1": "releases/validation-v1/manifest.json",
        },
    }
    content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    _write_immutable(path, content)


def freeze_validation_v1(project_root: Path | str) -> list[Path]:
    """Freeze and return the four canonical validation-v1 manifest paths."""

    root = Path(project_root).resolve()
    releases = [*(_split_release(root, spec) for spec in _SPLIT_SOURCES)]
    releases.append(_skillflow_release(root))
    paths: list[Path] = []
    for release in releases:
        path = _release_path(root, release)
        content = json.dumps(
            release.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        _write_immutable(path, content)
        _write_benchmark_metadata(root, release)
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    root = args.project_root.resolve()
    for path in freeze_validation_v1(root):
        print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
