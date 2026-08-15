import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    path = PROJECT_ROOT / "scripts/replay_fixed_skillopt_artifacts.py"
    assert path.is_file(), "fixed-artifact replay CLI is missing"
    spec = importlib.util.spec_from_file_location("replay_fixed_skillopt_artifacts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_artifact_arguments_resolves_paths_and_rejects_duplicate_labels(
    tmp_path: Path,
) -> None:
    module = _load_script()
    (tmp_path / "seed.md").write_text("seed\n", encoding="utf-8")
    (tmp_path / "candidate.md").write_text("candidate\n", encoding="utf-8")

    parsed = module.parse_artifact_arguments(
        ["seed=seed.md", "candidate=candidate.md"], project_root=tmp_path
    )

    assert parsed == {
        "seed": (tmp_path / "seed.md").resolve(),
        "candidate": (tmp_path / "candidate.md").resolve(),
    }
    with pytest.raises(ValueError, match="duplicate artifact label"):
        module.parse_artifact_arguments(
            ["seed=seed.md", "seed=candidate.md"], project_root=tmp_path
        )


def test_replay_plan_declares_counterbalanced_order_policy() -> None:
    module = _load_script()

    assert module.ORDER_POLICY == "cyclic_rotation"


def test_replay_cli_exposes_resume_flag() -> None:
    module = _load_script()

    args = module._parser().parse_args(
        [
            "--manifest",
            "manifest.json",
            "--artifact",
            "seed=seed.md",
            "--reference",
            "seed",
            "--output-dir",
            "run",
            "--resume",
        ]
    )

    assert args.resume is True
