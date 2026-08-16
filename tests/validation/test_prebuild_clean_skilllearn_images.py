import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
import pytest

from rsebench.evolution.skilllearn_executor import SkillLearnImageRecord
from rsebench.hashing import sha256_tree
from scripts import prebuild_clean_skilllearn_images as prebuild


def _release_test_module() -> ModuleType:
    path = Path(__file__).parents[1] / "selection/test_release.py"
    spec = importlib.util.spec_from_file_location("prebuild_release_fixtures", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load release fixtures: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE_FIXTURES = _release_test_module()


def _manifest(
    root: Path,
    family: str,
    task_ids: list[str],
    *,
    qualification_version: str = "clean-qualification-v1",
) -> Path:
    tasks = [
        {
            "task_id": task_id,
            "benchmark": "skilllearnbench",
            "domain": "skill_learning",
            "prompt": task_id,
            "gold_answers": [],
            "verifier": "skilllearn_hidden_test_v1",
            "source_hash": f"{index + 1}" * 64,
            "artifact_path": f"rsebench-methods://skilllearnbench/tasks/{family}/{task_id}",
            "metadata": {
                "task_family": family,
                "official_instance_path": f"rsebench-methods://skilllearnbench/tasks/{family}/{task_id}",
            },
        }
        for index, task_id in enumerate(task_ids)
    ]
    payload = {
        "benchmark": "skilllearnbench",
        "domain": "skill_learning",
        "seed": 7,
        "source_hash": "a" * 64,
        "train": tasks[:2],
        "validation": tasks[2:3],
        "clean_test": tasks[3:],
        "metadata": {
            "task_family": family,
            "qualification_version": qualification_version,
        },
    }
    path = root / f"{family}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_prebuild_traverses_in_order_and_deduplicates_contexts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_root = tmp_path / "manifests"
    manifest_root.mkdir()
    _manifest(
        manifest_root,
        "family-a",
        ["family-a-1", "family-a-2", "family-a-3", "family-a-4"],
    )
    _manifest(
        manifest_root,
        "family-b",
        ["family-b-1", "family-b-2", "family-b-3", "family-b-4"],
    )
    calls: list[str] = []

    class FakeBackend:
        def __init__(self, **kwargs):
            self.require_prebuilt = kwargs["require_prebuilt"]

        def prepare(self, task, output_dir):
            calls.append(task.task_id)
            context = "1" * 64 if task.task_id.endswith(("-1", "-2")) else "2" * 64
            return SkillLearnImageRecord(
                task_id=task.task_id,
                context_hash=context,
                image_tag=f"image:{context[:4]}",
                image_id=f"sha256:{context}",
                workdir="/workspace",
            )

    monkeypatch.setattr(prebuild, "DockerSkillLearnBackend", FakeBackend)
    monkeypatch.setattr(prebuild, "methods_root", lambda: tmp_path / "methods")
    monkeypatch.setattr(prebuild, "combined_method_env", lambda _: {})
    output = tmp_path / "image_manifest.json"

    payload = prebuild.prebuild_images(
        manifest_root=manifest_root,
        output=output,
    )

    assert calls == [
        "family-a-1",
        "family-a-2",
        "family-a-3",
        "family-a-4",
        "family-b-1",
        "family-b-2",
        "family-b-3",
        "family-b-4",
    ]
    assert len(payload["images"]) == 2
    assert len(payload["task_to_context_hash"]) == 8
    assert payload["all_ready"] is True


def test_prebuild_records_failure_and_raises(tmp_path: Path, monkeypatch) -> None:
    manifest_root = tmp_path / "manifests"
    manifest_root.mkdir()
    _manifest(
        manifest_root,
        "family-a",
        ["family-a-1", "family-a-2", "family-a-3", "family-a-4"],
    )

    class FailingBackend:
        def __init__(self, **kwargs):
            pass

        def prepare(self, task, output_dir):
            raise RuntimeError("docker build failed: dependency unavailable")

    monkeypatch.setattr(prebuild, "DockerSkillLearnBackend", FailingBackend)
    monkeypatch.setattr(prebuild, "methods_root", lambda: tmp_path / "methods")
    monkeypatch.setattr(prebuild, "combined_method_env", lambda _: {})
    output = tmp_path / "image_manifest.json"

    with pytest.raises(RuntimeError, match="dependency unavailable"):
        prebuild.prebuild_images(manifest_root=manifest_root, output=output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["all_ready"] is False
    assert payload["failures"][0]["status"] == "failed"
    assert "dependency unavailable" in payload["failures"][0]["stderr"]


def test_prepare_offline_verifier_wheelhouse_downloads_pins_and_hashes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        destination = Path(command[command.index("--dest") + 1])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "pytest-8.4.1-py3-none-any.whl").write_bytes(b"pytest")
        (destination / "pytest_json_ctrf-0.3.5-py3-none-any.whl").write_bytes(
            b"ctrf"
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(prebuild.subprocess, "run", fake_run)
    wheelhouse = tmp_path / "verifier-wheels"

    payload = prebuild.prepare_verifier_wheelhouse(wheelhouse)

    assert payload["mode"] == "offline_pytest"
    assert payload["packages"] == [
        "pytest==8.4.1",
        "pytest-json-ctrf==0.3.5",
    ]
    assert payload["wheel_requirements"] == [
        "pytest==8.4.1",
        "pytest-json-ctrf==0.3.5",
        "exceptiongroup==1.3.1",
        "tomli==2.0.1",
        "typing-extensions==4.15.0",
    ]
    assert payload["wheelhouse_hash"] == sha256_tree(wheelhouse)
    assert payload["wheels"] == [
        {
            "name": "pytest-8.4.1-py3-none-any.whl",
            "sha256": hashlib.sha256(b"pytest").hexdigest(),
        },
        {
            "name": "pytest_json_ctrf-0.3.5-py3-none-any.whl",
            "sha256": hashlib.sha256(b"ctrf").hexdigest(),
        },
    ]
    assert commands[0][-5:] == [
        "pytest==8.4.1",
        "pytest-json-ctrf==0.3.5",
        "exceptiongroup==1.3.1",
        "tomli==2.0.1",
        "typing-extensions==4.15.0",
    ]
    assert commands[0][:2] == ["pip", "download"]


def test_prebuild_derives_v2_version_and_supports_external_record_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_root = tmp_path / "manifests"
    manifest_root.mkdir()
    _manifest(
        manifest_root,
        "family-a",
        ["family-a-1", "family-a-2", "family-a-3", "family-a-4"],
        qualification_version="clean-qualification-v2",
    )
    record_roots = []

    class FakeBackend:
        def __init__(self, **kwargs):
            pass

        def prepare(self, task, output_dir):
            record_roots.append(output_dir)
            return SkillLearnImageRecord(
                task_id=task.task_id,
                context_hash="1" * 64,
                image_tag="image:fixture",
                image_id="sha256:" + "2" * 64,
                workdir="/workspace",
            )

    monkeypatch.setattr(prebuild, "DockerSkillLearnBackend", FakeBackend)
    monkeypatch.setattr(prebuild, "methods_root", lambda: tmp_path / "methods")
    output = tmp_path / "tracked/image_manifest.json"
    record_root = tmp_path / "untracked-records"

    payload = prebuild.prebuild_images(
        manifest_root=manifest_root,
        output=output,
        record_root=record_root,
    )

    assert payload["qualification_version"] == "clean-qualification-v2"
    assert all(path.is_relative_to(record_root) for path in record_roots)


def test_prebuild_selection_root_consumes_aggregate_candidate_and_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = RELEASE_FIXTURES.make_release_inputs()
    candidate = inputs["candidates"]["skilllearnbench"]
    confirmation = inputs["confirmations"]["skilllearnbench"]
    selection_root = tmp_path / "selection"
    candidate_path = selection_root / "candidates/skilllearnbench/candidate_1.json"
    confirmation_path = selection_root / "confirmation/skilllearnbench.json"
    candidate_path.parent.mkdir(parents=True)
    confirmation_path.parent.mkdir(parents=True)
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
    confirmation_path.write_text(confirmation.model_dump_json(), encoding="utf-8")
    (selection_root / "manifest.json").write_text(
        json.dumps(
            {
                "selection_version": "noise-screen-v1",
                "candidates": {
                    "skilllearnbench": [
                        candidate_path.relative_to(selection_root).as_posix()
                    ]
                },
                "confirmation": {
                    "skilllearnbench": confirmation_path.relative_to(
                        selection_root
                    ).as_posix()
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    class FakeBackend:
        def __init__(self, **kwargs):
            assert kwargs["require_prebuilt"] is True

        def prepare(self, task, output_dir):
            del output_dir
            calls.append(task.task_id)
            context_hash = hashlib.sha256(
                task.metadata["task_family"].encode()
            ).hexdigest()
            return SkillLearnImageRecord(
                task_id=task.task_id,
                context_hash=context_hash,
                image_tag=f"image:{context_hash[:8]}",
                image_id="sha256:" + context_hash,
                workdir="/workspace",
            )

    monkeypatch.setattr(prebuild, "DockerSkillLearnBackend", FakeBackend)
    output = tmp_path / "images.json"

    payload = prebuild.prebuild_selection_images(
        selection_root=selection_root,
        output=output,
        data_root=tmp_path / "data",
        methods_root_path=tmp_path / "methods",
        require_existing=True,
    )

    expected_ids = {
        task.task_id
        for split in (candidate, confirmation)
        for role in (
            ("train", "validation", "confirmation_test")
            if hasattr(split, "confirmation_test")
            else ("train", "validation", "qualification_test", "screening_test")
        )
        for task in getattr(split, role)
    }
    assert set(calls) == expected_ids
    assert set(payload["task_to_context_hash"]) == expected_ids
    assert payload["families"] == [
        *candidate.metadata["families"],
        *confirmation.metadata["families"],
    ]
    assert payload["selection_hashes"] == {
        "candidate": candidate.selection_hash,
        "confirmation": confirmation.selection_hash,
    }
    assert payload["provider_calls"] == 0
    assert payload["all_ready"] is True


def test_prebuild_cli_exposes_selection_root_without_provider_input() -> None:
    help_text = prebuild.build_parser().format_help()
    assert "--selection-root" in help_text
    assert "--manifest-root" in help_text
    assert "--input" not in help_text
