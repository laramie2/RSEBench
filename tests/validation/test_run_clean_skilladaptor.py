import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import (
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
)
from rsebench.evolution.skilladaptor_executor import SkillAdaptorBudget
from rsebench.selection import StableSplitCandidate
from scripts import run_clean_skilladaptor


RUNTIME = {
    "max_iterations": 3,
    "max_episode_steps": 15,
    "min_sample_size": 5,
}


def _task(task_id: str, *, benchmark: str = "webshop") -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark=benchmark,
        domain="interactive",
        prompt=f"buy product for {task_id}",
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
        verifier="webshop_official_reward_v1",
        metadata={"goal_idx": int(task_id.rsplit("_", 1)[1])},
    )


def _manifest(
    tmp_path: Path,
    *,
    benchmark: str = "webshop",
    sizes: tuple[int, int, int] = (5, 5, 20),
    runtime: dict[str, int] | None = None,
    qualification_version: str = "clean-qualification-v1",
) -> Path:
    train_size, validation_size, test_size = sizes
    cursor = 1

    def tasks(count: int) -> list[TaskManifest]:
        nonlocal cursor
        result = [
            _task(f"goal_{value}", benchmark=benchmark)
            for value in range(cursor, cursor + count)
        ]
        cursor += count
        return result

    split = CleanEvolutionSplitManifest(
        benchmark=benchmark,
        domain="interactive",
        seed=20260813,
        source_hash="a" * 64,
        train=tasks(train_size),
        validation=tasks(validation_size),
        clean_test=tasks(test_size),
        metadata={
            "runtime": runtime or RUNTIME,
            "qualification_version": qualification_version,
        },
    )
    path = tmp_path / "manifest.json"
    path.write_text(split.model_dump_json(indent=2), encoding="utf-8")
    return path


def _candidate_manifest(tmp_path: Path) -> Path:
    path = _manifest(tmp_path, qualification_version="noise-screen-v1")
    split = CleanEvolutionSplitManifest.model_validate_json(path.read_text())
    roles = {
        "train": split.train,
        "validation": split.validation,
        "qualification_test": split.clean_test,
        "screening_test": [_task("goal_31")],
    }
    candidate = StableSplitCandidate(
        benchmark=split.benchmark,
        domain=split.domain,
        candidate_index=2,
        source_hash=canonical_hash("candidate"),
        selection_hash=canonical_hash("selection"),
        metadata={
            **split.metadata,
            "selection_version": "noise-screen-v1",
            "source_seed": split.seed,
            "baseline": "skilladaptor",
        },
        **roles,
    )
    path.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_clean_skilladaptor_launcher_locks_budget_parameters_and_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}
    methods = tmp_path / "methods"
    (methods / "skilladaptor/skill-adaptor").mkdir(parents=True)
    (methods / "webshop").mkdir()
    seed = tmp_path / "seed.json"
    seed.write_text('{"skills": {}}', encoding="utf-8")

    class FakeExecutor:
        def __init__(self, **kwargs):
            captured["executor"] = kwargs

    class FakeRunner:
        def __init__(self, executor):
            captured["runner_executor"] = executor

        def run(self, **kwargs):
            captured["run"] = kwargs
            run_dir = Path(kwargs["output_root"]) / "run-1"
            run_dir.mkdir(parents=True)
            return SimpleNamespace(run_dir=str(run_dir))

    monkeypatch.setattr(run_clean_skilladaptor, "SkillAdaptorExecutor", FakeExecutor)
    monkeypatch.setattr(run_clean_skilladaptor, "CleanEvolutionRunner", FakeRunner)
    monkeypatch.setattr(run_clean_skilladaptor, "methods_root", lambda: methods)
    identity = object()
    attempt = object()
    monkeypatch.setattr(
        run_clean_skilladaptor,
        "load_runtime_identity",
        lambda **kwargs: (identity, attempt),
    )
    monkeypatch.setattr(
        run_clean_skilladaptor,
        "combined_method_env",
        lambda _: {"DEEPSEEK_API_KEY": "unused"},
    )

    run_dir = run_clean_skilladaptor.run_manifest(
        _manifest(tmp_path, qualification_version="clean-qualification-v2"),
        seed_skill=seed,
        method_seed=20260813,
        output_root=tmp_path / "runs",
    )

    assert run_dir.name == "run-1"
    assert captured["executor"]["budget"] == SkillAdaptorBudget(
        max_iterations=3,
        max_episode_steps=15,
    )
    assert captured["run"]["policy"] == CleanQualificationPolicy()
    assert captured["run"]["seed_skill_path"] == seed.resolve()
    assert captured["run"]["parameters"]["runtime"] == RUNTIME
    assert captured["run"]["parameters"]["retrieval_threshold"] == 0.10
    assert captured["run"]["parameters"]["patch_hashes"]
    assert (
        captured["run"]["parameters"]["qualification_version"]
        == "clean-qualification-v2"
    )
    assert captured["run"]["identity"] is identity
    assert captured["run"]["attempt"] is attempt


@pytest.mark.parametrize(
    ("benchmark", "sizes", "runtime", "message"),
    [
        ("other", (5, 5, 20), RUNTIME, "only supports WebShop"),
        ("webshop", (4, 5, 20), RUNTIME, "exact 5/5/20"),
        (
            "webshop",
            (5, 5, 20),
            {**RUNTIME, "max_episode_steps": 8},
            "runtime metadata differs",
        ),
    ],
)
def test_clean_skilladaptor_launcher_rejects_manifest_drift(
    tmp_path: Path,
    benchmark: str,
    sizes: tuple[int, int, int],
    runtime: dict[str, int],
    message: str,
) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        run_clean_skilladaptor.run_manifest(
            _manifest(
                tmp_path,
                benchmark=benchmark,
                sizes=sizes,
                runtime=runtime,
            ),
            seed_skill=seed,
            method_seed=20260813,
            output_root=tmp_path / "runs",
        )


def test_clean_skilladaptor_launcher_rejects_unfixed_method_seed(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported formal method seed"):
        run_clean_skilladaptor.run_manifest(
            _manifest(tmp_path),
            seed_skill=seed,
            method_seed=1,
            output_root=tmp_path / "runs",
        )


def test_noise_screen_skilladaptor_requires_runtime_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text("{}", encoding="utf-8")
    captured = {}

    class IdentityBoundaryReached(Exception):
        pass

    def capture(**kwargs):
        captured.update(kwargs)
        raise IdentityBoundaryReached

    monkeypatch.setattr(run_clean_skilladaptor, "load_runtime_identity", capture)

    with pytest.raises(IdentityBoundaryReached):
        run_clean_skilladaptor.run_manifest(
            _candidate_manifest(tmp_path),
            seed_skill=seed,
            method_seed=20260813,
            output_root=tmp_path / "runs",
        )

    assert captured["required"] is True
    assert captured["benchmark"] == "webshop"


def test_clean_skilladaptor_dry_run_makes_no_executor_or_provider_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text('{"skills": {}}', encoding="utf-8")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("dry run must not construct executor or provider env")

    monkeypatch.setattr(run_clean_skilladaptor, "SkillAdaptorExecutor", forbidden)
    monkeypatch.setattr(run_clean_skilladaptor, "combined_method_env", forbidden)

    run_dir = run_clean_skilladaptor.run_manifest(
        _manifest(tmp_path, qualification_version="noise-screen-v1"),
        seed_skill=seed,
        method_seed=20260813,
        output_root=tmp_path / "preflight",
        dry_run=True,
    )

    assert calls == []
    payload = json.loads((run_dir / "preflight.json").read_text(encoding="utf-8"))
    assert payload["task_counts"] == {
        "train": 5,
        "validation": 5,
        "clean_test": 20,
    }
    assert payload["runtime"] == RUNTIME
    assert payload["provider_calls"] == 0
    assert list(run_dir.rglob("*.jsonl")) == []


def test_webshop_v2_resolves_declared_v1_calibration_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = _manifest(tmp_path)
    split = CleanEvolutionSplitManifest.model_validate_json(
        manifest.read_text(encoding="utf-8")
    )
    split = split.model_copy(
        update={
            "metadata": {
                **split.metadata,
                "calibration_selection_path": (
                    "rsebench-project://benchmark/validation/clean_qualification_v1/"
                    "webshop_validation_selection.json"
                ),
            }
        }
    )
    monkeypatch.setattr(run_clean_skilladaptor, "PROJECT_ROOT", tmp_path)

    resolved = run_clean_skilladaptor._calibration_selection_path(manifest, split)

    assert resolved == (
        tmp_path
        / "benchmark/validation/clean_qualification_v1/"
        "webshop_validation_selection.json"
    )


def test_webshop_v2_calibration_uses_only_versioned_retrieval_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = _manifest(tmp_path, qualification_version="clean-qualification-v2")
    split = CleanEvolutionSplitManifest.model_validate_json(
        manifest.read_text(encoding="utf-8")
    )
    selected_ids = [int(task.task_id.removeprefix("goal_")) for task in split.validation]
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "selected_ids": selected_ids,
                "candidate_ids": selected_ids,
                "selected_seed_score": 0.4,
                "execution_failures": {},
                "uses_evolved_outcomes": False,
                "uses_clean_test_outcomes": False,
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text(
        "\n".join(
            json.dumps(event)
            for task in split.validation
            for event in (
                {
                    "episode_id": task.task_id,
                    "event": "retrieval",
                    "retrieved_skill_ids": ["seed"],
                },
                {
                    "episode_id": task.task_id,
                    "event": "prompt_injection",
                    "injected_skill_ids": ["seed"],
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    split = split.model_copy(
        update={
            "metadata": {
                **split.metadata,
                "calibration_selection_path": str(selection),
                "calibration_evidence_path": str(evidence),
                "calibration_evidence_hash": hashlib.sha256(
                    evidence.read_bytes()
                ).hexdigest(),
            }
        }
    )
    manifest.write_text(split.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(run_clean_skilladaptor, "PROJECT_ROOT", tmp_path)

    audit = run_clean_skilladaptor._calibration_evidence(manifest, split)

    assert audit["event_count"] == 10
    assert audit["selected_retrieval_audited"] is True
    assert audit["general_seed_reached_each_prompt"] is True
