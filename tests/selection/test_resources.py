from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from rsebench.hashing import sha256_file
from rsebench.selection.resources import (
    build_resource_lock,
    validate_resource_lock_materializations,
)


def _release_test_module() -> ModuleType:
    path = Path(__file__).with_name("test_release.py")
    spec = importlib.util.spec_from_file_location("resource_release_fixtures", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load release fixtures: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE_FIXTURES = _release_test_module()


def _git_repo(path: Path) -> str:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"], check=True
    )
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


@pytest.fixture
def resource_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    inputs = RELEASE_FIXTURES.make_release_inputs()
    selection_root = tmp_path / "selection"
    data_root = tmp_path / "data"
    methods_root = tmp_path / "methods"
    selection_root.mkdir()
    data_root.mkdir()
    methods_root.mkdir()
    candidates: dict[str, list[str]] = {}
    confirmations: dict[str, str] = {}
    all_tasks = []
    for benchmark in sorted(RELEASE_FIXTURES.DOMAINS):
        candidate_path = selection_root / "candidates" / benchmark / "candidate_1.json"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate = inputs["candidates"][benchmark]
        candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
        candidates[benchmark] = [candidate_path.relative_to(selection_root).as_posix()]
        confirmation_path = selection_root / "confirmation" / f"{benchmark}.json"
        confirmation_path.parent.mkdir(parents=True, exist_ok=True)
        confirmation = inputs["confirmations"][benchmark]
        confirmation_path.write_text(confirmation.model_dump_json(), encoding="utf-8")
        confirmations[benchmark] = confirmation_path.relative_to(selection_root).as_posix()
        for split in (candidate, confirmation):
            for role in (
                ("train", "validation", "confirmation_test")
                if hasattr(split, "confirmation_test")
                else ("train", "validation", "qualification_test", "screening_test")
            ):
                all_tasks.extend(getattr(split, role))
    (selection_root / "manifest.json").write_text(
        json.dumps({"candidates": candidates, "confirmation": confirmations}),
        encoding="utf-8",
    )
    for task in all_tasks:
        relative = task.artifact_path.removeprefix("rsebench-data://")
        materialized = data_root / relative
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_text(task.task_id, encoding="utf-8")

    registry_rows = []
    for baseline in sorted(RELEASE_FIXTURES.BASELINES):
        checkout = (
            "skilllearnbench"
            if baseline == "skilllearn_self_feedback"
            else baseline
        )
        revision = _git_repo(methods_root / checkout)
        registry_rows.extend(
            [
                f"  {baseline}:",
                f"    repository: https://github.com/example/{baseline}.git",
                f"    commit: {revision}",
            ]
        )
    registry = tmp_path / "methods.yaml"
    registry.write_text(
        "version: 1\nmethods:\n" + "\n".join(registry_rows) + "\n",
        encoding="utf-8",
    )
    skill_ids = sorted(
        task.task_id for task in all_tasks if task.benchmark == "skilllearnbench"
    )
    image_manifest = tmp_path / "images.json"
    image_manifest.write_text(
        json.dumps(
            {
                "all_ready": True,
                "images": [
                    {
                        "context_hash": "8" * 64,
                        "image_tag": "fixture:latest",
                        "image_id": "sha256:" + "7" * 64,
                        "task_ids": skill_ids,
                    }
                ],
                "task_to_context_hash": {task_id: "8" * 64 for task_id in skill_ids},
            }
        ),
        encoding="utf-8",
    )
    return selection_root, data_root, methods_root, registry, image_manifest


def test_build_resource_lock_covers_and_verifies_materializations(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture

    lock = build_resource_lock(
        selection_root=selection_root,
        data_root=data_root,
        methods_root=methods_root,
        methods_registry=registry,
        image_manifest=image_manifest,
    )

    validate_resource_lock_materializations(
        lock,
        data_root=data_root,
        methods_root=methods_root,
        methods_registry=registry,
        image_manifest=image_manifest,
    )
    data_ref = next(resource for resource in lock.resources if resource.kind == "rsebench-data")
    assert data_ref.sha256 == sha256_file(
        data_root / data_ref.uri.removeprefix("rsebench-data://")
    )
    assert {
        resource.materialization
        for resource in lock.resources
        if resource.kind == "git"
    } == {
        "rsebench-methods://skillopt",
        "rsebench-methods://skilladaptor",
        "rsebench-methods://skilllearn_self_feedback",
    }
    image = next(
        resource for resource in lock.resources if resource.kind == "external-image"
    )
    assert image.sha256 == "7" * 64
    assert image.task_ids


def test_resource_lock_detects_local_hash_drift(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    lock = build_resource_lock(
        selection_root=selection_root,
        data_root=data_root,
        methods_root=methods_root,
        methods_registry=registry,
        image_manifest=image_manifest,
    )
    resource = next(row for row in lock.resources if row.kind == "rsebench-data")
    path = data_root / resource.uri.removeprefix("rsebench-data://")
    path.write_text("drift", encoding="utf-8")

    with pytest.raises(ValueError, match="materialization hash differs"):
        validate_resource_lock_materializations(
            lock,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=image_manifest,
        )


def test_resource_lock_detects_git_revision_drift(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    lock = build_resource_lock(
        selection_root=selection_root,
        data_root=data_root,
        methods_root=methods_root,
        methods_registry=registry,
        image_manifest=image_manifest,
    )
    repository = methods_root / "skillopt"
    (repository / "README.md").write_text("next\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "next"], check=True)

    with pytest.raises(ValueError, match="git revision differs"):
        validate_resource_lock_materializations(
            lock,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=image_manifest,
        )


def test_resource_lock_detects_untracked_baseline_materialization_drift(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    lock = build_resource_lock(
        selection_root=selection_root,
        data_root=data_root,
        methods_root=methods_root,
        methods_registry=registry,
        image_manifest=image_manifest,
    )
    (methods_root / "skilladaptor" / "new_patch_file.py").write_text(
        "patched = True\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="git materialization differs"):
        validate_resource_lock_materializations(
            lock,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=image_manifest,
        )


def test_resource_lock_rejects_image_manifest_digest_drift(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    lock = build_resource_lock(
        selection_root=selection_root,
        data_root=data_root,
        methods_root=methods_root,
        methods_registry=registry,
        image_manifest=image_manifest,
    )
    payload = json.loads(image_manifest.read_text(encoding="utf-8"))
    payload["images"][0]["image_id"] = "sha256:" + "9" * 64
    image_manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="external-image.*manifest"):
        validate_resource_lock_materializations(
            lock,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=image_manifest,
        )


def test_resource_lock_rejects_nonunique_image_task_context_mapping(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    payload = json.loads(image_manifest.read_text(encoding="utf-8"))
    task_id = next(iter(payload["task_to_context_hash"]))
    payload["task_to_context_hash"][task_id] = "9" * 64
    image_manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="context mapping"):
        build_resource_lock(
            selection_root=selection_root,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=image_manifest,
        )


def test_resource_lock_rejects_task_repeated_across_image_rows(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    payload = json.loads(image_manifest.read_text(encoding="utf-8"))
    duplicate = dict(payload["images"][0])
    duplicate["context_hash"] = "9" * 64
    duplicate["image_id"] = "sha256:" + "9" * 64
    payload["images"].append(duplicate)
    image_manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="multiple contexts"):
        build_resource_lock(
            selection_root=selection_root,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=image_manifest,
        )


def test_resource_lock_fails_closed_without_image_manifest(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    lock = build_resource_lock(
        selection_root=selection_root,
        data_root=data_root,
        methods_root=methods_root,
        methods_registry=registry,
        image_manifest=image_manifest,
    )

    missing_manifest = image_manifest.with_name("missing.json")
    with pytest.raises(FileNotFoundError):
        validate_resource_lock_materializations(
            lock,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=missing_manifest,
        )
    assert not missing_manifest.exists()


def test_resource_lock_rejects_descendant_local_symlink(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    first_task = RELEASE_FIXTURES.make_release_inputs()["candidates"][
        "webshop"
    ].train[0]
    materialized = data_root / first_task.artifact_path.removeprefix(
        "rsebench-data://"
    )
    materialized.unlink()
    materialized.mkdir()
    outside = data_root.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (materialized / "escape").symlink_to(outside)

    with pytest.raises(ValueError, match="descendant symlink"):
        build_resource_lock(
            selection_root=selection_root,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=image_manifest,
        )


def test_resource_lock_rejects_descendant_git_symlink(
    resource_fixture: tuple[Path, Path, Path, Path, Path],
) -> None:
    selection_root, data_root, methods_root, registry, image_manifest = resource_fixture
    outside = methods_root / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (methods_root / "skillopt" / "escape").symlink_to(outside)

    with pytest.raises(ValueError, match="descendant symlink"):
        build_resource_lock(
            selection_root=selection_root,
            data_root=data_root,
            methods_root=methods_root,
            methods_registry=registry,
            image_manifest=image_manifest,
        )
