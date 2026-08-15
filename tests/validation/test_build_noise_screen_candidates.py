from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.selection import ExposureRegistry
from scripts.build_noise_screen_candidates import load_repository_bundles


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _task(task_id: str, role: str, root: Path) -> TaskManifest:
    artifact = root / "data" / f"{task_id}.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}\n", encoding="utf-8")
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="spreadsheet",
        prompt=f"lookup and join fixture {task_id}",
        verifier="fixture_verifier_v1",
        source_hash=canonical_hash([task_id]),
        artifact_path=str(artifact.resolve()),
        metadata={
            "role": role,
            "static_applicability": {"N1": True, "N2": True},
        },
    )


def _write_json(path: Path, payload: object) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    elif isinstance(payload, list):
        payload = [
            row.model_dump(mode="json") if hasattr(row, "model_dump") else row
            for row in payload
        ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data_root = tmp_path / "data"
    methods_root = tmp_path / "methods"
    methods_root.mkdir()
    clean = CleanEvolutionSplitManifest(
        benchmark="fixture",
        domain="spreadsheet",
        seed=7,
        source_hash="a" * 64,
        train=[_task("clean-train", "train", tmp_path)],
        validation=[_task("clean-validation", "validation", tmp_path)],
        clean_test=[_task("qualification", "test", tmp_path)],
        metadata={"qualification_version": "clean-qualification-v2"},
    )
    clean_path = tmp_path / "clean.json"
    _write_json(clean_path, clean)
    pools: dict[str, Path] = {}
    for role, count in (("train", 4), ("validation", 2), ("test", 3)):
        path = tmp_path / f"{role}.json"
        _write_json(
            path,
            [_task(f"source-{role}-{index}", role, tmp_path) for index in range(count)],
        )
        pools[role] = path
    config = tmp_path / "sources.json"
    _write_json(
        config,
        {
            "benchmarks": {
                "fixture": {
                    "clean_split": clean_path.name,
                    "source_pools": {
                        role: path.name for role, path in pools.items()
                    },
                    "counts": {"train": 1, "validation": 1, "test": 1},
                }
            }
        },
    )
    exposure = tmp_path / "exposure.json"
    registry = ExposureRegistry(records=[], registry_hash=canonical_hash([]))
    _write_json(exposure, registry)
    return config, exposure, data_root, methods_root


def test_cli_writes_byte_stable_portable_candidates_without_provider_calls(
    tmp_path: Path,
) -> None:
    config, exposure, data_root, methods_root = _fixture(tmp_path)
    output = tmp_path / "out"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/build_noise_screen_candidates.py"),
        "--exposure",
        str(exposure),
        "--data-root",
        str(data_root),
        "--methods-root",
        str(methods_root),
        "--output",
        str(output),
        "--source-config",
        str(config),
    ]
    environment = dict(os.environ)
    environment.update(
        {
            "OPENAI_API_KEY": "must-not-be-used",
            "DEEPSEEK_API_KEY": "must-not-be-used",
        }
    )

    first = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    first_files = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in sorted(output.rglob("*.json"))
    }
    second = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert first_files == {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in sorted(output.rglob("*.json"))
    }
    assert sorted(first_files) == [
        "candidate_audits/fixture/candidate_1.json",
        "candidate_audits/fixture/candidate_2.json",
        "candidate_audits/fixture/candidate_3.json",
        "candidates/fixture/candidate_1.json",
        "candidates/fixture/candidate_2.json",
        "candidates/fixture/candidate_3.json",
        "confirmation/fixture.json",
        "confirmation_seal.json",
        "manifest.json",
    ]
    serialized = b"".join(first_files.values()).decode("utf-8")
    assert str(tmp_path.resolve()) not in serialized
    assert "rsebench-data://" in serialized
    assert "must-not-be-used" not in serialized
    audit = json.loads(
        first_files["candidate_audits/fixture/candidate_1.json"]
    )
    assert audit["static_gates"]["noise_applicability"]["N1"]["status"] == "pass"
    assert audit["static_gates"]["noise_applicability"]["N2"]["status"] == "pass"
    assert audit["static_gates"]["noise_applicability"]["N3"]["status"] == "pending"
    assert audit["static_gates"]["noise_applicability"]["N4"]["status"] == "pending"
    assert first.stdout == second.stdout
    assert "provider_calls=0" in first.stdout


def test_cli_refuses_to_replace_different_existing_bytes(tmp_path: Path) -> None:
    config, exposure, data_root, methods_root = _fixture(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    (output / "manifest.json").write_text("{}\n", encoding="utf-8")
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/build_noise_screen_candidates.py"),
        "--exposure",
        str(exposure),
        "--data-root",
        str(data_root),
        "--methods-root",
        str(methods_root),
        "--output",
        str(output),
        "--source-config",
        str(config),
    ]

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "different candidate manifest already exists" in result.stderr


def test_repository_loader_exercises_real_local_materializations() -> None:
    registry = ExposureRegistry(records=[], registry_hash=canonical_hash([]))

    bundles = load_repository_bundles(
        exposure_registry=registry,
        data_root=PROJECT_ROOT / "data",
        methods_root=PROJECT_ROOT / "methods/external",
    )

    assert set(bundles) == {
        "spreadsheetbench_verified",
        "officeqa_full",
        "webshop",
        "skilllearnbench",
    }
    assert [len(row.train) for row in bundles["spreadsheetbench_verified"].candidates] == [
        20,
        20,
        20,
    ]
    assert [len(row.train) for row in bundles["officeqa_full"].candidates] == [
        12,
        12,
        12,
    ]
    assert [len(row.train) for row in bundles["webshop"].candidates] == [5, 5, 5]
    assert len(bundles["skilllearnbench"].candidates) == 1
    assert bundles["skilllearnbench"].confirmation.metadata["families"] == [
        "court-form-filling",
        "earthquake-plate-calculation",
        "dbscan-parameter-tuning",
        "travel-planning",
    ]
