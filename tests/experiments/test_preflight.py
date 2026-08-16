from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from rsebench.experiments.bootstrap import BaselineFingerprint
from rsebench.experiments.preflight import load_experiment_matrix, preflight_matrix


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _fixture_project(tmp_path: Path) -> tuple[Path, Path, BaselineFingerprint]:
    root = tmp_path / "project"
    (root / "src/rsebench").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "benchmark").mkdir()
    (root / "configs").mkdir()
    (root / "src/rsebench/__init__.py").write_text("", encoding="utf-8")
    (root / "scripts/run_fixture.py").write_text("# fixture\n", encoding="utf-8")
    seed = root / "benchmark/seed.md"
    seed.write_text("seed skill\n", encoding="utf-8")
    provider = root / "configs/provider.yaml"
    provider.write_text(
        yaml.safe_dump(
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_env": "FIXTURE_API_KEY",
                "temperature": 0.0,
                "thinking": "disabled",
            }
        ),
        encoding="utf-8",
    )
    def task(task_id: str) -> dict[str, object]:
        return {
            "task_id": task_id,
            "benchmark": "fixture",
            "domain": "document",
            "prompt": task_id,
            "gold_answers": ["answer"],
            "source_hash": _hash(task_id),
        }
    manifest = root / "benchmark/fixture.json"
    manifest.write_text(
        json.dumps(
            {
                "benchmark": "fixture",
                "domain": "document",
                "seed": 7,
                "source_hash": _hash("split"),
                "train": [task("train")],
                "validation": [task("validation")],
                "clean_test": [task("test")],
                "metadata": {
                    "qualification_version": "clean-qualification-v2",
                    "runtime": {"workers": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    matrix = root / "configs/matrix.yaml"
    matrix.write_text(
        yaml.safe_dump(
            {
                "schema_version": "rsebench.experiment-matrix.v1",
                "qualification_version": "clean-qualification-v2",
                "stage": "clean",
                "method_seeds": [20260813, 20260814, 20260815],
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "temperature": 0.0,
                "thinking": "disabled",
                "provider_config": "configs/provider.yaml",
                "output_root": "outputs/fixture",
                "cells": [
                    {
                        "key": "fixture",
                        "benchmark": "fixture",
                        "baseline": "fixture",
                        "launcher": "scripts/run_fixture.py",
                        "manifest": "benchmark/fixture.json",
                        "seed_skill": "benchmark/seed.md",
                        "seed_skill_argument": True,
                        "task_counts": {
                            "train": 1,
                            "validation": 1,
                            "clean_test": 1,
                        },
                        "runtime": {"workers": 1},
                        "adapter_key": "fixture",
                        "adapter_max_parallel": 2,
                        "mutable_resource_keys": [],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "RSEBench Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fixture")
    fingerprint = BaselineFingerprint(
        baseline="fixture",
        repository="https://example.com/fixture.git",
        upstream_revision="1" * 40,
        patch_paths=[],
        patch_hashes=[],
        patchset_hash="2" * 64,
        python_version="3.13.5",
        fingerprint="3" * 64,
    )
    return root, matrix, fingerprint


def test_preflight_builds_three_identities_without_provider_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared-but-never-read")

    report = preflight_matrix(
        matrix,
        project_root=root,
        package_file=root / "src/rsebench/__init__.py",
        fingerprint_resolver=lambda baseline: fingerprint,
    )

    assert report.provider_calls == 0
    assert report.all_ready is True
    assert len(report.units) == 3
    assert len({unit.identity.experiment_id for unit in report.units}) == 3
    assert all(unit.task_order_hash == report.units[0].task_order_hash for unit in report.units)
    assert all(unit.scheduled.mutable_resource_keys == [] for unit in report.units)
    assert all(unit.scheduled.identity == unit.identity for unit in report.units)
    assert len({unit.scheduled.output_dir for unit in report.units}) == 3
    assert report.provider_configuration.credential_name == "FIXTURE_API_KEY"
    assert report.provider_configuration.credential_declared is True
    assert not (root / "outputs/fixture").exists()


def _convert_fixture_to_noise_candidate(
    root: Path,
    matrix_path: Path,
    *,
    matrix_candidate_index: int,
    manifest_candidate_index: int,
    declared_manifest_candidate_index: int,
) -> None:
    matrix_payload = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_payload["qualification_version"] = "noise-screen-v1"
    matrix_payload["candidate_index"] = matrix_candidate_index
    matrix_payload["cells"][0]["manifest_candidate_index"] = (
        declared_manifest_candidate_index
    )
    matrix_path.write_text(
        yaml.safe_dump(matrix_payload, sort_keys=False),
        encoding="utf-8",
    )
    manifest_path = root / "benchmark/fixture.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    qualification_test = manifest_payload.pop("clean_test")
    source_seed = manifest_payload.pop("seed")
    manifest_payload.update(
        {
            "schema_version": "rsebench.stable-split-candidate.v1",
            "candidate_index": manifest_candidate_index,
            "qualification_test": qualification_test,
            "screening_test": [
                {
                    "task_id": "screening",
                    "benchmark": "fixture",
                    "domain": "document",
                    "prompt": "screening",
                    "gold_answers": ["answer"],
                    "source_hash": _hash("screening"),
                }
            ],
            "selection_hash": _hash("selection"),
        }
    )
    manifest_payload["metadata"].update(
        {
            "qualification_version": "noise-screen-v1",
            "selection_version": "noise-screen-v1",
            "source_seed": source_seed,
            "baseline": "fixture",
        }
    )
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")


def test_preflight_accepts_matrix_declared_noise_screen_version(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix_path, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    _convert_fixture_to_noise_candidate(
        root,
        matrix_path,
        matrix_candidate_index=2,
        manifest_candidate_index=2,
        declared_manifest_candidate_index=2,
    )
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "noise screen fixture")

    result = preflight_matrix(
        matrix_path,
        project_root=root,
        package_file=root / "src/rsebench/__init__.py",
        fingerprint_resolver=lambda baseline: fingerprint,
    )

    assert result.provider_calls == 0
    assert result.units[0].identity.inputs.stage == "clean"


@pytest.mark.parametrize(
    ("matrix_candidate_index", "manifest_candidate_index"),
    [(2, 3), (3, 2)],
)
def test_preflight_rejects_swapped_candidate_manifest_before_identity_generation(
    monkeypatch,
    tmp_path: Path,
    matrix_candidate_index: int,
    manifest_candidate_index: int,
) -> None:
    root, matrix_path, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    _convert_fixture_to_noise_candidate(
        root,
        matrix_path,
        matrix_candidate_index=matrix_candidate_index,
        manifest_candidate_index=manifest_candidate_index,
        declared_manifest_candidate_index=matrix_candidate_index,
    )
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "swapped candidate fixture")

    with pytest.raises(ValueError, match="manifest candidate index differs"):
        preflight_matrix(
            matrix_path,
            project_root=root,
            package_file=root / "src/rsebench/__init__.py",
            fingerprint_resolver=lambda baseline: fingerprint,
        )


def test_noise_screen_matrix_requires_manifest_candidate_index_per_cell(
    tmp_path: Path,
) -> None:
    _, matrix_path, _ = _fixture_project(tmp_path)
    matrix_payload = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_payload["qualification_version"] = "noise-screen-v1"
    matrix_payload["candidate_index"] = 2
    matrix_path.write_text(
        yaml.safe_dump(matrix_payload, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest_candidate_index"):
        load_experiment_matrix(matrix_path)


@pytest.mark.parametrize(
    ("cell_index", "manifest_candidate_index"),
    [(0, 3), (3, 3)],
)
def test_candidate2_matrix_rejects_undeclared_manifest_candidate_exceptions(
    tmp_path: Path,
    cell_index: int,
    manifest_candidate_index: int,
) -> None:
    matrix_path = tmp_path / "matrix.yaml"
    payload = yaml.safe_load(
        (
            PROJECT_ROOT
            / "configs/experiments/noise-screen-v1-candidate2.yaml"
        ).read_text(encoding="utf-8")
    )
    payload["cells"][cell_index]["manifest_candidate_index"] = (
        manifest_candidate_index
    )
    matrix_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="manifest_candidate_index differs from matrix candidate_index",
    ):
        load_experiment_matrix(matrix_path)


def test_preflight_rejects_manifest_version_different_from_matrix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix_path, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    manifest_path = root / "benchmark/fixture.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["metadata"]["qualification_version"] = "noise-screen-v1"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "mismatched manifest version")

    with pytest.raises(ValueError, match="manifest qualification version differs"):
        preflight_matrix(
            matrix_path,
            project_root=root,
            package_file=root / "src/rsebench/__init__.py",
            fingerprint_resolver=lambda baseline: fingerprint,
        )


def test_preflight_rejects_arbitrary_matrix_qualification_version(
    tmp_path: Path,
) -> None:
    _, matrix_path, _ = _fixture_project(tmp_path)
    matrix_payload = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_payload["qualification_version"] = "future-version"
    matrix_path.write_text(
        yaml.safe_dump(matrix_payload, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="qualification_version"):
        load_experiment_matrix(matrix_path)


def test_preflight_rejects_zero_clean_test_outside_skilllearn_validation(
    tmp_path: Path,
) -> None:
    _, matrix_path, _ = _fixture_project(tmp_path)
    matrix_payload = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_payload["cells"][0]["task_counts"]["clean_test"] = 0
    matrix_path.write_text(
        yaml.safe_dump(matrix_payload, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="zero clean_test is only valid"):
        load_experiment_matrix(matrix_path)


@pytest.mark.parametrize(
    ("cell_index", "wrong_counts"),
    [
        (0, {"train": 20, "validation": 11, "clean_test": 30}),
        (1, {"train": 12, "validation": 6, "clean_test": 20}),
    ],
)
def test_matrix_rejects_wrong_declared_skillopt_task_counts(
    tmp_path: Path,
    cell_index: int,
    wrong_counts: dict[str, int],
) -> None:
    matrix_path = tmp_path / "matrix.yaml"
    payload = yaml.safe_load(
        (PROJECT_ROOT / "configs/experiments/clean-v2.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload["cells"][cell_index]["task_counts"] = wrong_counts
    matrix_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="SkillOpt task counts differ"):
        load_experiment_matrix(matrix_path)


@pytest.mark.parametrize("candidate_index", [0, 4])
def test_preflight_rejects_out_of_range_candidate_index(
    tmp_path: Path,
    candidate_index: int,
) -> None:
    _, matrix_path, _ = _fixture_project(tmp_path)
    matrix_payload = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_payload["candidate_index"] = candidate_index
    matrix_path.write_text(
        yaml.safe_dump(matrix_payload, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="candidate_index"):
        load_experiment_matrix(matrix_path)


def test_preflight_rejects_dirty_repository_before_identity_generation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    (root / "scripts/run_fixture.py").write_text("# dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="clean git worktree"):
        preflight_matrix(
            matrix,
            project_root=root,
            package_file=root / "src/rsebench/__init__.py",
            fingerprint_resolver=lambda baseline: fingerprint,
        )


def test_preflight_rejects_output_outside_project_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    payload = yaml.safe_load(matrix.read_text(encoding="utf-8"))
    payload["output_root"] = "../escaped"
    matrix.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    _git(root, "add", str(matrix.relative_to(root)))
    _git(root, "commit", "-q", "-m", "change output")

    with pytest.raises(ValueError, match="output_root must be inside"):
        preflight_matrix(
            matrix,
            project_root=root,
            package_file=root / "src/rsebench/__init__.py",
            fingerprint_resolver=lambda baseline: fingerprint,
        )


def test_canary_matrix_expands_only_the_cell_selected_seed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root, matrix, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    payload = yaml.safe_load(matrix.read_text(encoding="utf-8"))
    payload["purpose"] = "canary"
    payload["cells"][0]["method_seeds"] = [20260814]
    matrix.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    _git(root, "add", str(matrix.relative_to(root)))
    _git(root, "commit", "-q", "-m", "select canary seed")

    report = preflight_matrix(
        matrix,
        project_root=root,
        package_file=root / "src/rsebench/__init__.py",
        fingerprint_resolver=lambda baseline: fingerprint,
    )

    assert [unit.method_seed for unit in report.units] == [20260814]


def test_formal_matrix_rejects_per_cell_seed_selection(tmp_path: Path) -> None:
    root, matrix, _ = _fixture_project(tmp_path)
    payload = yaml.safe_load(matrix.read_text(encoding="utf-8"))
    payload["cells"][0]["method_seeds"] = [20260814]
    matrix.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="formal matrix cannot override cell seeds"):
        load_experiment_matrix(matrix)


def test_clean_v2_matrix_declares_four_portable_cells() -> None:
    matrix = load_experiment_matrix(
        PROJECT_ROOT / "configs/experiments/clean-v2.yaml"
    )

    assert [cell.benchmark for cell in matrix.cells] == [
        "spreadsheetbench_verified",
        "officeqa_full",
        "webshop",
        "skilllearnbench",
    ]
    assert all(
        cell.manifest.startswith("benchmark/validation/clean_qualification_v2/")
        for cell in matrix.cells
    )
    skillopt = [cell for cell in matrix.cells if cell.baseline == "skillopt"]
    assert len(skillopt) == 2
    assert all(cell.mutable_resource_keys == [] for cell in skillopt)
    skilllearn = matrix.cells[-1]
    assert skilllearn.family == "offer-letter-generator"
    assert "{method_seed}" in skilllearn.mutable_resource_keys[0]


def test_skilllearn_expanded_clean_matrix_declares_eight_families() -> None:
    matrix = load_experiment_matrix(
        PROJECT_ROOT / "configs/experiments/skilllearn-clean-expanded-v1.yaml"
    )

    assert matrix.qualification_version == "clean-qualification-v2"
    assert matrix.method_seeds == [20260813, 20260814, 20260815]
    assert len(matrix.cells) == 8
    assert {cell.family for cell in matrix.cells} == {
        "dependency-vulnerability-check",
        "enterprise-information-search",
        "financial-analysis",
        "github-repo-analytics",
        "offer-letter-generator",
        "organize-messy-files",
        "schedule-planning",
        "stock-data-visualization",
    }
    assert all(cell.benchmark == "skilllearnbench" for cell in matrix.cells)
    assert all(cell.baseline == "skilllearn_self_feedback" for cell in matrix.cells)
    assert all(cell.adapter_max_parallel == 3 for cell in matrix.cells)
    assert sum(cell.task_counts.train for cell in matrix.cells) == 16
    assert sum(cell.task_counts.validation for cell in matrix.cells) == 8
    assert sum(cell.task_counts.clean_test for cell in matrix.cells) == 20
    assert all(
        cell.manifest.startswith(
            "benchmark/validation/clean_qualification_v2/skilllearnbench/"
        )
        for cell in matrix.cells
    )
    assert all("{method_seed}" in cell.mutable_resource_keys[0] for cell in matrix.cells)


def test_skilllearn_round2_matrices_declare_twelve_formal_and_two_replay_units() -> None:
    formal = load_experiment_matrix(
        PROJECT_ROOT / "configs/experiments/skilllearn-clean-expansion-round2.yaml"
    )
    replay = load_experiment_matrix(
        PROJECT_ROOT / "configs/experiments/skilllearn-offer-replay-round2.yaml"
    )

    assert formal.purpose == "formal"
    assert formal.qualification_version == "clean-qualification-v2"
    assert formal.stage == "clean"
    assert formal.model == "deepseek-v4-flash"
    assert [cell.family for cell in formal.cells] == [
        "court-form-filling",
        "earthquake-plate-calculation",
        "dbscan-parameter-tuning",
        "travel-planning",
    ]
    assert all(cell.method_seeds is None for cell in formal.cells)
    assert all(cell.adapter_max_parallel == 3 for cell in formal.cells)
    assert sum(len(formal.method_seeds) for _ in formal.cells) == 12

    assert replay.purpose == "canary"
    assert [cell.family for cell in replay.cells] == [
        "offer-letter-generator",
        "offer-letter-generator",
    ]
    assert [cell.method_seeds for cell in replay.cells] == [
        [20260813],
        [20260814],
    ]
    assert sum(len(cell.method_seeds or []) for cell in replay.cells) == 2
    assert all(cell.adapter_max_parallel == 3 for cell in replay.cells)

    all_cells = [*formal.cells, *replay.cells]
    assert all(cell.baseline == "skilllearn_self_feedback" for cell in all_cells)
    assert all(
        cell.image_manifest
        == "outputs/preflight/skilllearn-clean-expansion-round2/image_manifest.json"
        for cell in all_cells
    )
    assert all(
        cell.manifest.startswith(
            "benchmark/validation/skilllearn_clean_expansion_v1/skilllearnbench/"
        )
        for cell in all_cells
    )


def test_noise_screen_candidate_matrix_declares_candidate_index() -> None:
    matrix = load_experiment_matrix(
        PROJECT_ROOT / "configs/experiments/noise-screen-v1-candidate2.yaml"
    )

    assert matrix.qualification_version == "noise-screen-v1"
    assert matrix.candidate_index == 2
    assert len(matrix.cells) == 7
    assert {
        cell.key: cell.manifest_candidate_index for cell in matrix.cells
    } == {
        "spreadsheet-candidate2-skillopt": 2,
        "officeqa-candidate2-skillopt": 2,
        "webshop-candidate2-skilladaptor": 2,
        "skilllearn-organize-messy-files": 1,
        "skilllearn-offer-letter-generator": 1,
        "skilllearn-schedule-planning": 1,
        "skilllearn-dependency-vulnerability-check": 1,
    }


def test_clean_v2_canary_matrix_selects_one_preregistered_seed_per_cell() -> None:
    matrix = load_experiment_matrix(
        PROJECT_ROOT / "configs/experiments/clean-v2-canary.yaml"
    )

    assert matrix.purpose == "canary"
    assert {cell.key: cell.method_seeds for cell in matrix.cells} == {
        "spreadsheet-skillopt": [20260814],
        "officeqa-skillopt": [20260813],
        "webshop-skilladaptor": [20260815],
        "skilllearn-offer-letter": [20260813],
    }


def test_officeqa_retry_canary_contains_only_the_affected_cell() -> None:
    matrix = load_experiment_matrix(
        PROJECT_ROOT
        / "configs/experiments/clean-v2-canary-officeqa-retry.yaml"
    )

    assert matrix.purpose == "canary"
    assert [(cell.key, cell.method_seeds) for cell in matrix.cells] == [
        ("officeqa-skillopt", [20260813])
    ]
