import json
from pathlib import Path
import pytest

from rsebench.evolution.skilllearn_executor import SkillLearnImageRecord
from scripts import prebuild_clean_skilllearn_images as prebuild


def _manifest(root: Path, family: str, task_ids: list[str]) -> Path:
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
        "metadata": {"task_family": family},
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
