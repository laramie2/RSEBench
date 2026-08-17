#!/usr/bin/env python3
"""Freeze validated method releases and candidate lifecycle metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from rsebench.datasets import EvidenceReference
from rsebench.experiments.bootstrap import load_patch_series
from rsebench.methods import (
    HarnessIdentity,
    PatchIdentity,
    ProviderIdentity,
    build_method_release,
)


_ACTIVE_RELEASES: tuple[dict[str, Any], ...] = (
    {
        "release_id": "skillopt-spreadsheet-validation-v1",
        "filename": "spreadsheet-validation-v1.json",
        "method": "skillopt",
        "repository": "https://github.com/microsoft/SkillOpt.git",
        "revision": "47fe269d75d3def79ffd90236261d26d84868ae5",
        "dataset": "spreadsheetbench-verified-validation-v1",
        "fingerprint": "b209b2686c902166e31062e6473075f5a87d1058759d81ce66f6864efafcc3a3",
        "patch_count": 4,
        "harness": "skillopt.engine.trainer:Trainer",
        "smoke": ("python", "scripts/run_clean_skillopt.py", "--help"),
        "clean_cell": "spreadsheet-skillopt",
    },
    {
        "release_id": "skillopt-officeqa-validation-v1",
        "filename": "officeqa-validation-v1.json",
        "method": "skillopt",
        "repository": "https://github.com/microsoft/SkillOpt.git",
        "revision": "47fe269d75d3def79ffd90236261d26d84868ae5",
        "dataset": "officeqa-full-validation-v1",
        "fingerprint": "bbf775793ff2cc1e9f22b2c530a82957ba87d05749a50f6f53657c01549d9033",
        "patch_count": 5,
        "harness": "skillopt.engine.trainer:Trainer",
        "smoke": ("python", "scripts/run_clean_skillopt.py", "--help"),
        "clean_cell": "officeqa-skillopt",
    },
    {
        "release_id": "skilladaptor-webshop-validation-v1",
        "filename": "webshop-validation-v1.json",
        "method": "skilladaptor",
        "repository": "https://github.com/zjunlp/SkillAdaptor.git",
        "revision": "b26d1ab5a798f07e53048b5ff509e8535e9fa228",
        "dataset": "webshop-validation-v1",
        "fingerprint": "ebcfa0ccc76c5589bd95da3e7ae21a4065dd5e060f9abc207954e4cd750ef014",
        "patch_count": 6,
        "harness": "skill-adaptor.run_skill_adaptor:main",
        "smoke": ("python", "scripts/run_clean_skilladaptor.py", "--help"),
        "clean_cell": "webshop-skilladaptor",
    },
    {
        "release_id": "skillflow-validation-v1",
        "filename": "skillflow-validation-v1.json",
        "method": "skillflow",
        "repository": "https://github.com/ZhangZi-a/SkillFlow.git",
        "revision": "7b49ff5a7e26cd7706e959bfa0dba4746d18440d",
        "dataset": "skillflow-tasks-validation-v1",
        "fingerprint": "e329b830e2a65748f5fc8736a2dd7f56781a28f400281b9ee608a85c98aca875",
        "patch_count": 5,
        "harness": "iterative_shared_skills_runner:main",
        "smoke": ("python", "scripts/run_skillflow_clean.py", "--help"),
        "clean_cell": "skillflow-three-family-selection",
    },
)

_SKILLLEARN_RELEASE = {
    "release_id": "skilllearn-self-feedback-diagnostic-v1",
    "filename": "diagnostic-v1.json",
    "method": "skilllearn_self_feedback",
    "repository": "https://github.com/cxcscmu/SkillLearnBench.git",
    "revision": "a0da045a8bf64b8a8ff20730c4d6ef10dc4e2c5b",
    "dataset": "skilllearnbench-diagnostic-clean-v2",
    "fingerprint": "033cc887ba59a8692a7c416f0a050dff37f086e4d8715b690096189a8df1ebf7",
    "patch_count": 1,
    "harness": "baselines.self_feedback:main",
    "smoke": ("python", "scripts/run_clean_skilllearn.py", "--help"),
    "clean_cell": "skilllearn-offer-letter",
}

_CANDIDATES = (
    "trace2skill",
    "skillgrad",
    "evoskill",
    "skills_coach",
    "coevoskills",
    "federatedskill",
    "skillsbench",
    "skilllearn_teacher_feedback",
    "rethinkskill",
)

_LOCAL_CHECKOUT = {
    "skilllearn_self_feedback": "skilllearnbench",
    "skilllearn_teacher_feedback": "skilllearnbench",
}

_CLEAN_EVIDENCE = (
    "releases/diagnostic/clean-v2-canaries/manifest.json",
    "24621ac4edcd4f75dab89f1e558b96bd2695140bcc61758adfdc718f514ff3ab",
)

_SKILLFLOW_EVIDENCE = (
    (
        "benchmark/validation/skillflow_clean_qualification_v1/noise_validation_selection.json",
        "1d7caec1bd273a742e7c62467c9b694b0c7b8cbf17bb61fab2e7723fa2a2b0d7",
    ),
    (
        "benchmark/validation/skillflow_clean_qualification_v1/second_family_candidates_batch2.json",
        "205fea257c57537e8f7ea54f3fcc97530106d6a0b43202a717f17504c2476016",
    ),
)


def _write_immutable(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RuntimeError(f"refusing to overwrite different frozen content: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _yaml(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _registry(root: Path) -> dict[str, dict[str, Any]]:
    payload = yaml.safe_load(
        (root / "benchmark/registry/methods.yaml").read_text(encoding="utf-8")
    )
    return payload["methods"]


def _verified_evidence(root: Path, rows: tuple[tuple[str, str], ...]):
    evidence: list[EvidenceReference] = []
    for relative, expected in rows:
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"clean evidence hash differs for {relative}")
        evidence.append(
            EvidenceReference(
                uri=f"rsebench-project://{relative}",
                sha256=expected,
                kind="clean-control",
            )
        )
    return tuple(evidence)


def _patches(root: Path, spec: dict[str, Any]) -> tuple[PatchIdentity, ...]:
    method = spec["method"]
    series_path = root / f"methods/validated/{method}/patches/series.yaml"
    series = load_patch_series(series_path)
    entries = series.patches[: int(spec["patch_count"])]
    return tuple(
        PatchIdentity(
            uri=(
                f"rsebench-project://methods/validated/{method}/patches/{entry.path}"
            ),
            sha256=entry.sha256,
            purpose=entry.purpose,
        )
        for entry in entries
    )


def _write_method_support_files(
    root: Path,
    spec: dict[str, Any],
    *,
    status: str,
    release_ids: tuple[str, ...],
) -> None:
    method = spec["method"]
    base = root / "methods/validated" / method
    _write_immutable(
        base / "method.yaml",
        _yaml(
            {
                "schema_version": "rsebench.method.v1",
                "method": method,
                "status": status,
                "upstream_repository": spec["repository"],
                "upstream_revision": spec["revision"],
                "code_status": "validated_method_owned_harness",
                "local_checkout": _LOCAL_CHECKOUT.get(method, method),
                "releases": list(release_ids),
            }
        ),
    )
    _write_immutable(
        base / "upstream.lock",
        _yaml(
            {
                "repository": spec["repository"],
                "revision": spec["revision"],
                "source_policy": "clone-on-bootstrap-do-not-vendor",
            }
        ),
    )
    _write_immutable(
        base / "integration/environment.lock",
        _yaml(
            {
                "schema_version": "rsebench.method-environment.v1",
                "python": "3.13.9",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "provider_config": (
                    "rsebench-project://configs/pilot/deepseek-v4-flash-4096.yaml"
                ),
                "provider_config_sha256": (
                    "97b4bdb24f2a9e1d49d5cf5a74951b3c9abf7fc5b4fcfef90caa793b100c92dc"
                ),
                "dependency_policy": "upstream-lock-plus-pinned-patch-series",
            }
        ),
    )


def _release(root: Path, spec: dict[str, Any], *, status: str):
    if spec["method"] == "skillflow":
        evidence_rows = _SKILLFLOW_EVIDENCE
    else:
        evidence_rows = (_CLEAN_EVIDENCE,)
    return build_method_release(
        release_id=spec["release_id"],
        method=spec["method"],
        status=status,
        upstream_repository=spec["repository"],
        upstream_revision=spec["revision"],
        patch_series=_patches(root, spec),
        harness=HarnessIdentity(
            entrypoint=spec["harness"],
            version="validation-v1",
            fingerprint=spec["fingerprint"],
        ),
        provider=ProviderIdentity(
            family="openai-compatible",
            model="deepseek-v4-flash",
            adapter=f"{spec['method']}.deepseek-v4-flash",
        ),
        environment_lock=(
            f"rsebench-project://methods/validated/{spec['method']}"
            "/integration/environment.lock"
        ),
        supported_datasets=(spec["dataset"],),
        clean_evidence=_verified_evidence(root, evidence_rows),
        smoke_command=spec["smoke"],
        baseline_fingerprint=spec["fingerprint"],
        metadata={
            "clean_control_cell": spec["clean_cell"],
            "harness_ownership": "method-owned",
        },
    )


def freeze_method_releases(project_root: Path | str) -> list[Path]:
    root = Path(project_root).resolve()
    registry = _registry(root)
    outputs: list[Path] = []

    by_method: dict[str, list[dict[str, Any]]] = {}
    for spec in _ACTIVE_RELEASES:
        by_method.setdefault(spec["method"], []).append(spec)
    for method, specs in by_method.items():
        ordered = sorted(specs, key=lambda row: row["filename"])
        _write_method_support_files(
            root,
            ordered[0],
            status="active",
            release_ids=tuple(row["release_id"] for row in ordered),
        )
        for spec in ordered:
            release = _release(root, spec, status="active")
            path = root / f"methods/validated/{method}/releases/{spec['filename']}"
            _write_immutable(path, _json(release.model_dump(mode="json")))
            outputs.append(path)

    inactive = _SKILLLEARN_RELEASE
    _write_method_support_files(
        root,
        inactive,
        status="validated_inactive",
        release_ids=(inactive["release_id"],),
    )
    inactive_release = _release(root, inactive, status="validated_inactive")
    inactive_path = (
        root
        / "methods/validated/skilllearn_self_feedback/releases"
        / inactive["filename"]
    )
    _write_immutable(inactive_path, _json(inactive_release.model_dump(mode="json")))
    outputs.append(inactive_path)

    for method in _CANDIDATES:
        specification = registry[method]
        path = root / "methods/candidates" / method / "method.yaml"
        _write_immutable(
            path,
            _yaml(
                {
                    "schema_version": "rsebench.method.v1",
                    "method": method,
                    "status": "candidate",
                    "upstream_repository": specification["repository"],
                    "upstream_revision": specification["commit"],
                    "code_status": specification["code_status"],
                    "local_checkout": _LOCAL_CHECKOUT.get(method, method),
                    "releases": [],
                }
            ),
        )
        outputs.append(path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    root = args.project_root.resolve()
    for path in freeze_method_releases(root):
        print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
