import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.evolution.runner import EvaluationResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    path = PROJECT_ROOT / "scripts/replay_fixed_skillopt_artifacts.py"
    assert path.is_file(), "fixed-artifact replay CLI is missing"
    spec = importlib.util.spec_from_file_location("replay_fixed_skillopt_artifacts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(tmp_path: Path) -> Path:
    def task(task_id: str) -> TaskManifest:
        return TaskManifest(
            task_id=task_id,
            benchmark="spreadsheetbench_verified",
            domain="spreadsheet",
            prompt=task_id,
            gold_answers=["ok"],
            source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
        )

    split = CleanEvolutionSplitManifest(
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        seed=20260813,
        source_hash="a" * 64,
        train=[task("train")],
        validation=[task("validation")],
        clean_test=[task("test")],
        metadata={
            "runtime": {
                "max_steps": 3,
                "batch_size": 4,
                "workers": 2,
                "max_tool_turns": 3,
                "max_completion_tokens": 2048,
            }
        },
    )
    path = tmp_path / "manifest.json"
    path.write_text(split.model_dump_json(indent=2), encoding="utf-8")
    return path


class _FakeSkillOptExecutor:
    def __init__(self, **_kwargs) -> None:
        self.timing = None

    def configure_token_run(self, _output_dir: Path) -> None:
        pass

    def configure_timing(self, recorder) -> None:
        self.timing = recorder

    def evaluate(
        self,
        *,
        skill_path: Path,
        clean_test: list[TaskManifest],
        output_dir: Path,
        stage: str,
    ) -> EvaluationResult:
        assert skill_path.is_file()
        assert self.timing is not None
        output_dir.mkdir(parents=True)
        scores = {}
        for task in clean_test:
            with self.timing.span(
                level="task", name=stage, task_id=task.task_id
            ):
                scores[task.task_id] = 1.0
        return EvaluationResult(score=1.0, per_task_scores=scores)


def _configure_cli(module, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "SkillOptExecutor", _FakeSkillOptExecutor)
    monkeypatch.setattr(module, "methods_root", lambda: tmp_path / "methods")
    monkeypatch.setattr(
        module,
        "combined_method_env",
        lambda _method: {"RSEBENCH_DATA_ROOT": str(tmp_path / "data")},
    )
    monkeypatch.setattr(
        module,
        "resolve_clean_split_paths",
        lambda split, **_kwargs: split,
    )


def _run_cli(module, monkeypatch, arguments: list[str]) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["replay_fixed_skillopt_artifacts.py", *arguments],
    )
    module.main()


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


def test_skillopt_replay_cli_exposes_explicit_evaluation_role() -> None:
    module = _load_script()

    args = module._parser().parse_args(
        [
            "--manifest",
            "candidate.json",
            "--evaluation-role",
            "screening_test",
            "--artifact",
            "seed=seed.md",
            "--reference",
            "seed",
            "--output-dir",
            "run",
        ]
    )

    assert args.evaluation_role == "screening_test"


def test_initial_dry_run_does_not_block_subsequent_live_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    _configure_cli(module, tmp_path, monkeypatch)
    artifact = tmp_path / "seed.md"
    artifact.write_text("seed\n", encoding="utf-8")
    output_dir = tmp_path / "replay"
    common = [
        "--manifest",
        str(_manifest(tmp_path)),
        "--artifact",
        f"seed={artifact}",
        "--reference",
        "seed",
        "--repeats",
        "3",
        "--output-dir",
        str(output_dir),
    ]

    _run_cli(module, monkeypatch, [*common, "--dry-run"])
    assert not output_dir.exists()
    assert output_dir.with_name("replay.plan.json").is_file()
    _run_cli(module, monkeypatch, [*common, "--confirm-provider-cost"])

    assert (output_dir / "result.json").is_file()
    assert json.loads((output_dir / "plan.json").read_text(encoding="utf-8"))[
        "provider_calls"
    ] is None


@pytest.mark.parametrize(
    ("field_path", "changed_value"),
    [
        (("split_source_hash",), "b" * 64),
        (("runtime", "workers"), 99),
        (("runtime", "max_tool_turns"), 99),
        (("runtime", "max_completion_tokens"), 99),
        (("model",), "other-model"),
        (("temperature",), 0.5),
        (("thinking",), "enabled"),
    ],
)
def test_resume_rejects_changed_effective_configuration_without_overwriting_plan(
    tmp_path: Path,
    monkeypatch,
    field_path: tuple[str, ...],
    changed_value: object,
) -> None:
    module = _load_script()
    _configure_cli(module, tmp_path, monkeypatch)
    artifact = tmp_path / "seed.md"
    artifact.write_text("seed\n", encoding="utf-8")
    output_dir = tmp_path / "replay"
    common = [
        "--manifest",
        str(_manifest(tmp_path)),
        "--artifact",
        f"seed={artifact}",
        "--reference",
        "seed",
        "--output-dir",
        str(output_dir),
    ]
    _run_cli(
        module,
        monkeypatch,
        [*common, "--repeats", "3", "--confirm-provider-cost"],
    )
    plan_path = output_dir / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    target = plan
    for field in field_path[:-1]:
        target = target[field]
    target[field_path[-1]] = changed_value
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    original_plan = plan_path.read_bytes()

    with pytest.raises(ValueError, match="resume preflight mismatch"):
        _run_cli(
            module,
            monkeypatch,
            [
                *common,
                "--repeats",
                "5",
                "--resume",
                "--confirm-provider-cost",
            ],
        )

    assert plan_path.read_bytes() == original_plan


def test_compatible_resume_retains_original_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    _configure_cli(module, tmp_path, monkeypatch)
    artifact = tmp_path / "seed.md"
    artifact.write_text("seed\n", encoding="utf-8")
    output_dir = tmp_path / "replay"
    common = [
        "--manifest",
        str(_manifest(tmp_path)),
        "--artifact",
        f"seed={artifact}",
        "--reference",
        "seed",
        "--output-dir",
        str(output_dir),
        "--confirm-provider-cost",
    ]
    _run_cli(module, monkeypatch, [*common, "--repeats", "3"])
    original_plan = (output_dir / "plan.json").read_bytes()

    _run_cli(
        module,
        monkeypatch,
        [*common, "--repeats", "5", "--resume"],
    )

    assert (output_dir / "plan.json").read_bytes() == original_plan
    assert json.loads((output_dir / "result.json").read_text(encoding="utf-8"))[
        "repeat_count"
    ] == 5
    assert output_dir.with_name("replay.resume-plan.json").is_file()


def test_replay_cli_rejects_non_preregistered_repeat_counts(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    artifact = tmp_path / "seed.md"
    artifact.write_text("seed\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--manifest",
            str(_manifest(tmp_path)),
            "--artifact",
            f"seed={artifact}",
            "--reference",
            "seed",
            "--repeats",
            "2",
            "--output-dir",
            str(tmp_path / "replay"),
            "--dry-run",
        ],
    )

    with pytest.raises(ValueError, match="exactly 3 or 5"):
        module.main()
