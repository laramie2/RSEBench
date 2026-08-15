import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_cli_builds_portable_byte_stable_registry(tmp_path: Path) -> None:
    manifest_root = tmp_path / "manifest-root"
    result_root = tmp_path / "result-root"
    manifest_root.mkdir()
    result_root.mkdir()
    (manifest_root / "manifest.json").write_text(
        json.dumps({"benchmark": "webshop", "train": ["goal_1"]}),
        encoding="utf-8",
    )
    (result_root / "result.json").write_text(
        json.dumps({"benchmark": "webshop", "per_task_scores": {"goal_1": 1.0}}),
        encoding="utf-8",
    )
    output = tmp_path / "registry.json"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/build_noise_screen_exposure.py"),
        "--source",
        f"main-manifests={manifest_root}:manifest_only",
        "--source",
        f"main-results={result_root}:score_observed",
        "--output",
        str(output),
    ]

    first = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    first_bytes = output.read_bytes()
    second = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert output.read_bytes() == first_bytes
    payload = json.loads(first_bytes)
    assert payload["records"] == [
        {
            "benchmark": "webshop",
            "first_experiment_id": None,
            "last_experiment_id": None,
            "level": "score_observed",
            "roles": ["per_task_scores", "train"],
            "source_partition": "train",
            "sources": ["main-manifests", "main-results"],
            "task_id": "goal_1",
        }
    ]
    serialized = first_bytes.decode("utf-8")
    assert str(manifest_root.resolve()) not in serialized
    assert str(result_root.resolve()) not in serialized
    assert first.stdout == second.stdout
    assert "1 exposure records" in first.stdout
