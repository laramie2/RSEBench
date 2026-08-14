import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution.contracts import ArmTaskRef, EvolutionArmManifest
from rsebench.evolution.skillopt_executor import (
    SkillOptBudget,
    SkillOptExecutor,
    _result_task_ids,
)


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="officeqa_full",
        domain="document",
        prompt=f"question {task_id}",
        gold_answers=["answer"],
        source_hash=(task_id.encode().hex() + "0" * 64)[:64],
        metadata={"gold_document_ids": ["docs/report.txt"]},
    )


def _office_executor_root(tmp_path: Path) -> tuple[Path, Path]:
    method_root = tmp_path / "skillopt"
    (method_root / ".venv/bin").mkdir(parents=True)
    (method_root / ".venv/bin/python").write_text("", encoding="utf-8")
    (method_root / "scripts").mkdir()
    (method_root / "scripts/train.py").write_text("", encoding="utf-8")
    (method_root / "scripts/eval_only.py").write_text("", encoding="utf-8")
    (method_root / "configs/officeqa").mkdir(parents=True)
    (method_root / "configs/officeqa/default.yaml").write_text(
        "env: {name: officeqa}", encoding="utf-8"
    )
    data_root = tmp_path / "data"
    (data_root / "materialized/officeqa_full/corpus").mkdir(parents=True)
    (data_root / "materialized/officeqa_full/parsed/jsons").mkdir(parents=True)
    return method_root, data_root


def _write_results(path: Path, task_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"id": task_id}) + "\n" for task_id in task_ids),
        encoding="utf-8",
    )


def test_skillopt_evolution_audits_native_train_and_validation_ids(
    tmp_path: Path,
) -> None:
    method_root, data_root = _office_executor_root(tmp_path)
    train_ids = [f"t{index:02d}" for index in range(1, 21)]
    validation_ids = [f"v{index:02d}" for index in range(1, 11)]

    def fake_run(command, **kwargs):
        out_root = Path(command[command.index("--out_root") + 1])
        out_root.mkdir(parents=True)
        (out_root / "best_skill.md").write_text("evolved", encoding="utf-8")
        (out_root / "summary.json").write_text(
            json.dumps(
                {
                    "total_accepts": 2,
                    "total_rejects": 1,
                    "total_steps": 3,
                    "baseline_selection_hard": 0.4,
                    "best_selection_hard": 0.6,
                }
            ),
            encoding="utf-8",
        )
        for step, ids in enumerate(
            (train_ids[:7], train_ids[7:14], train_ids[14:]), start=1
        ):
            _write_results(
                out_root / f"steps/step_{step:02d}/rollout/results.jsonl", ids
            )
        _write_results(
            out_root / "selection_eval_baseline/results.jsonl", validation_ids
        )
        _write_results(
            out_root / "steps/step_01/selection_eval/results.jsonl",
            validation_ids,
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=data_root,
        budget=SkillOptBudget(max_steps=3, batch_size=7, workers=2),
        command_runner=fake_run,
        environment={"DEEPSEEK_API_KEY": "secret"},
    )
    seed = tmp_path / "seed.md"
    seed.write_text("seed", encoding="utf-8")
    arm = EvolutionArmManifest(
        arm="clean",
        benchmark="officeqa_full",
        domain="document",
        method="skillopt",
        method_seed=20260813,
        split_seed=7,
        split_source_hash="2" * 64,
        seed_skill_hash="1" * 64,
        train=[
            ArmTaskRef(
                pair_id=f"{task_id}-pair",
                task_id=task_id,
                payload_hash="3" * 64,
            )
            for task_id in train_ids
        ],
        validation=[
            ArmTaskRef(
                pair_id=f"{task_id}-pair",
                task_id=task_id,
                payload_hash="4" * 64,
            )
            for task_id in validation_ids
        ],
        clean_test=[],
    )
    split = SimpleNamespace(
        benchmark="officeqa_full",
        train=[
            SimpleNamespace(clean=_task(task_id), noisy=_task(task_id))
            for task_id in train_ids
        ],
        validation=[
            SimpleNamespace(clean=_task(task_id), noisy=_task(task_id))
            for task_id in validation_ids
        ],
        clean_test=[],
        source_hash="4" * 64,
    )

    artifact = executor.evolve(
        arm=arm,
        split=split,
        seed_skill_path=seed,
        output_dir=tmp_path / "run/clean",
    )

    assert artifact.execution_audit is not None
    assert set(artifact.execution_audit.train_task_ids) == set(train_ids)
    assert set(artifact.execution_audit.validation_task_ids) == set(validation_ids)
    assert artifact.execution_audit.accepted_update_count == 2
    assert artifact.execution_audit.metadata["total_steps"] == 3
    assert artifact.execution_audit.metadata["total_rejects"] == 1


def test_skillopt_execution_result_requires_a_task_id(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="SkillOpt execution result lacks task ID"):
        _result_task_ids([results])


def test_officeqa_evaluation_types_only_native_execution_failures(
    tmp_path: Path,
) -> None:
    method_root, data_root = _office_executor_root(tmp_path)

    def fake_run(command, **kwargs):
        out_root = Path(command[command.index("--out_root") + 1])
        out_root.mkdir(parents=True)
        rows = [
            {
                "id": "provider",
                "hard": 0,
                "agent_ok": False,
                "failure_category": "provider_failure",
                "fail_reason": "request timed out",
            },
            {
                "id": "tool",
                "hard": 0,
                "agent_ok": False,
                "failure_category": "tool_budget_exhausted",
                "fail_reason": "turn limit",
            },
            {
                "id": "incorrect",
                "hard": 0,
                "agent_ok": True,
                "failure_category": "incorrect_answer",
                "predicted_answer": "wrong",
            },
        ]
        (out_root / "results.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=data_root,
        command_runner=fake_run,
        environment={"DEEPSEEK_API_KEY": "secret"},
    )
    skill = tmp_path / "skill.md"
    skill.write_text("skill", encoding="utf-8")
    evaluation = executor.evaluate(
        skill_path=skill,
        clean_test=[_task("provider"), _task("tool"), _task("incorrect")],
        output_dir=tmp_path / "evaluation",
        stage="clean",
    )

    assert set(evaluation.per_task_scores) == {"provider", "tool", "incorrect"}
    assert set(evaluation.diagnostics["execution_failures"]) == {"provider", "tool"}
    assert evaluation.diagnostics["execution_failures"]["provider"] == (
        "provider_failure: request timed out"
    )
    assert evaluation.diagnostics["systemic_failure_rate"] == pytest.approx(2 / 3)


def test_skillopt_executor_runs_native_train_and_parses_eval(
    tmp_path: Path, monkeypatch
):
    method_root = tmp_path / "skillopt"
    (method_root / ".venv" / "bin").mkdir(parents=True)
    (method_root / "scripts").mkdir()
    (method_root / "configs" / "officeqa").mkdir(parents=True)
    (method_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    (method_root / "scripts" / "train.py").write_text("", encoding="utf-8")
    (method_root / "scripts" / "eval_only.py").write_text("", encoding="utf-8")
    (method_root / "configs" / "officeqa" / "default.yaml").write_text(
        "env: {name: officeqa}", encoding="utf-8"
    )
    (tmp_path / "data" / "materialized" / "officeqa_full" / "corpus").mkdir(
        parents=True
    )
    (tmp_path / "data" / "materialized" / "officeqa_full" / "parsed/jsons").mkdir(
        parents=True
    )
    commands = []
    command_envs = []

    def fake_run(command, **kwargs):
        commands.append(command)
        command_envs.append(kwargs["env"])
        out_root = Path(command[command.index("--out_root") + 1])
        out_root.mkdir(parents=True, exist_ok=True)
        if command[1].endswith("train.py"):
            (out_root / "best_skill.md").write_text("evolved", encoding="utf-8")
            (out_root / "summary.json").write_text(
                json.dumps({"total_steps": 1}), encoding="utf-8"
            )
        else:
            split_dir = Path(command[command.index("--split_dir") + 1])
            items = json.loads(
                (split_dir / "test" / "items.json").read_text(encoding="utf-8")
            )
            (out_root / "results.jsonl").write_text(
                "".join(
                    json.dumps(
                        {
                            "id": item["id"],
                            "hard": int(index == 0),
                            "exact": int(index == 0),
                            "predicted_answer": "answer" if index == 0 else "wrong",
                            "failure_category": "correct"
                            if index == 0
                            else "incorrect_answer",
                            "oracle_parsed_pages_included": True,
                            "oracle_parsed_pages_chars": 100,
                            "agent_ok": True,
                            "n_turns": 2,
                        }
                    )
                    + "\n"
                    for index, item in enumerate(items)
                ),
                encoding="utf-8",
            )
            (out_root / "eval_summary.json").write_text(
                json.dumps({"hard": 0.5}), encoding="utf-8"
            )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=tmp_path / "data",
        budget=SkillOptBudget(max_steps=1, batch_size=2, workers=1),
        command_runner=fake_run,
        environment={"DEEPSEEK_API_KEY": "must-not-be-written"},
    )
    monkeypatch.chdir(tmp_path)
    run_dir = Path("paired-run")
    run_dir.mkdir()
    executor.configure_token_run(run_dir)
    seed = tmp_path / "seed.md"
    seed.write_text("seed", encoding="utf-8")
    arm = EvolutionArmManifest(
        arm="clean",
        benchmark="officeqa_full",
        domain="document",
        method="skillopt",
        method_seed=11,
        split_seed=7,
        split_source_hash="2" * 64,
        seed_skill_hash="1" * 64,
        train=[ArmTaskRef(pair_id="a-pair", task_id="a", payload_hash="3" * 64)],
        validation=[],
        clean_test=[
            ArmTaskRef(pair_id="clean-test-t1", task_id="t1", payload_hash="4" * 64),
            ArmTaskRef(pair_id="clean-test-t2", task_id="t2", payload_hash="5" * 64),
        ],
        parameters={},
    )
    split = SimpleNamespace(
        benchmark="officeqa_full",
        train=[SimpleNamespace(clean=_task("a"), noisy=_task("a"))],
        validation=[],
        clean_test=[_task("t1"), _task("t2")],
        source_hash="4" * 64,
    )

    artifact = executor.evolve(
        arm=arm,
        split=split,
        seed_skill_path=seed,
        output_dir=run_dir / "clean",
    )
    evaluation = executor.evaluate(
        skill_path=Path(artifact.skill_path),
        clean_test=split.clean_test,
        output_dir=run_dir / "clean" / "clean_test_evaluation",
        stage="clean",
    )

    assert Path(artifact.skill_path).read_text(encoding="utf-8") == "evolved"
    assert evaluation.score == 0.5
    assert evaluation.per_task_scores == {"t1": 1.0, "t2": 0.0}
    assert evaluation.diagnostics["parseable_answer_rate"] == 1.0
    assert evaluation.diagnostics["oracle_parsed_pages_rate"] == 1.0
    assert evaluation.diagnostics["failure_category_counts"] == {
        "correct": 1,
        "incorrect_answer": 1,
    }
    assert all(
        any("openai_compatible" in arg for arg in command) for command in commands
    )
    assert command_envs[0]["RSEBENCH_TOKEN_LEDGER_DIR"] == str(
        (run_dir / "token_usage").resolve()
    )
    assert command_envs[0]["RSEBENCH_TOKEN_RUN_ID"] == "paired-run"
    assert command_envs[0]["RSEBENCH_TOKEN_DOMAIN"] == "document"
    assert command_envs[0]["RSEBENCH_TOKEN_BENCHMARK"] == "officeqa_full"
    assert command_envs[0]["RSEBENCH_TOKEN_ARM"] == "clean"
    assert command_envs[0]["RSEBENCH_TOKEN_STAGE"] == "evolution"
    assert command_envs[1]["RSEBENCH_TOKEN_ARM"] == "clean"
    assert command_envs[1]["RSEBENCH_TOKEN_STAGE"] == "eval"
    for command in commands:
        assert Path(command[command.index("--out_root") + 1]).is_absolute()
        split_flag = "--split_dir" if "--split_dir" in command else None
        if split_flag:
            assert Path(command[command.index(split_flag) + 1]).is_absolute()
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in (run_dir / "clean").rglob("*")
        if path.is_file()
    )
    assert "must-not-be-written" not in persisted


def test_skillopt_noisy_runtime_arm_exposes_only_requested_evidence_spec(
    tmp_path: Path,
):
    method_root = tmp_path / "skillopt"
    (method_root / ".venv/bin").mkdir(parents=True)
    (method_root / ".venv/bin/python").write_text("", encoding="utf-8")
    (method_root / "scripts").mkdir()
    (method_root / "scripts/train.py").write_text("", encoding="utf-8")
    (method_root / "configs/officeqa").mkdir(parents=True)
    (method_root / "configs/officeqa/default.yaml").write_text(
        "env: {name: officeqa}", encoding="utf-8"
    )
    data_root = tmp_path / "data"
    (data_root / "materialized/officeqa_full/corpus").mkdir(parents=True)
    (data_root / "materialized/officeqa_full/parsed/jsons").mkdir(parents=True)
    project_root = tmp_path / "project"
    spec = project_root / "benchmark/core1/runtime/officeqa_full/N3.json"
    spec.parent.mkdir(parents=True)
    spec.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs["env"])
        out_root = Path(command[command.index("--out_root") + 1])
        out_root.mkdir(parents=True)
        (out_root / "best_skill.md").write_text("evolved", encoding="utf-8")
        (out_root / "summary.json").write_text(
            json.dumps({"total_steps": 1, "total_accepts": 0}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=data_root,
        project_root=project_root,
        command_runner=fake_run,
        environment={"DEEPSEEK_API_KEY": "secret"},
    )
    seed = tmp_path / "seed.md"
    seed.write_text("seed", encoding="utf-8")
    arm = EvolutionArmManifest(
        arm="noisy",
        benchmark="officeqa_full",
        domain="document",
        method="skillopt",
        method_seed=11,
        split_seed=7,
        split_source_hash="2" * 64,
        seed_skill_hash="1" * 64,
        train=[
            ArmTaskRef(
                pair_id="a-pair",
                task_id="a",
                payload_hash="3" * 64,
                noise_id="officeqa-n3-a",
            )
        ],
        validation=[],
        clean_test=[],
        parameters={"stage": "N3"},
    )
    split = SimpleNamespace(
        benchmark="officeqa_full",
        train=[SimpleNamespace(clean=_task("a"), noisy=_task("a"))],
        validation=[],
        clean_test=[],
        source_hash="4" * 64,
    )

    executor.evolve(
        arm=arm,
        split=split,
        seed_skill_path=seed,
        output_dir=tmp_path / "run/noisy",
    )

    assert captured["RSEBENCH_EVIDENCE_SPEC"] == str(spec)
    assert captured["RSEBENCH_EVIDENCE_AUDIT_ROOT"] == str(
        (tmp_path / "run/noisy").resolve()
    )
    assert captured["RSEBENCH_EVIDENCE_ARM"] == "noisy"


def test_skillopt_executor_selects_dapo_config(tmp_path: Path):
    method_root = tmp_path / "skillopt"
    (method_root / ".venv" / "bin").mkdir(parents=True)
    (method_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    config = method_root / "configs" / "dapo" / "default.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("env: {name: dapo}", encoding="utf-8")

    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=tmp_path / "data",
        environment={"DEEPSEEK_API_KEY": "secret"},
    )

    assert executor._config("dapo_fixed_1000") == config
    assert "env.max_turns=3" in executor._domain_options("dapo_fixed_1000")


def test_skillopt_executor_exposes_officeqa_oracle_parsed_root(tmp_path: Path):
    method_root = tmp_path / "skillopt"
    (method_root / ".venv/bin").mkdir(parents=True)
    (method_root / ".venv/bin/python").write_text("", encoding="utf-8")
    corpus = tmp_path / "data/materialized/officeqa_full/corpus"
    parsed = tmp_path / "data/materialized/officeqa_full/parsed"
    corpus.mkdir(parents=True)
    (parsed / "jsons").mkdir(parents=True)
    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=tmp_path / "data",
        environment={"DEEPSEEK_API_KEY": "secret"},
    )

    options = executor._domain_options("officeqa_full")
    assert f"env.data_dirs={corpus},{parsed}" in options
    assert "evaluation.gate_metric=hard" in options


def test_skillopt_executor_selects_docvqa_config(tmp_path: Path):
    method_root = tmp_path / "skillopt"
    (method_root / ".venv" / "bin").mkdir(parents=True)
    (method_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    config = method_root / "configs" / "docvqa" / "default.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("env: {name: docvqa}", encoding="utf-8")
    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=tmp_path / "data",
        environment={"DEEPSEEK_API_KEY": "secret"},
    )

    assert executor._config("docvqa_10pct") == config
    assert "env.image_detail=high" in executor._domain_options("docvqa_10pct")


def test_skillopt_executor_selects_searchqa_config(tmp_path: Path):
    method_root = tmp_path / "skillopt"
    (method_root / ".venv" / "bin").mkdir(parents=True)
    (method_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    config = method_root / "configs" / "searchqa" / "default.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("env: {name: searchqa}", encoding="utf-8")
    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=tmp_path / "data",
        environment={"DEEPSEEK_API_KEY": "secret"},
    )

    assert executor._config("searchqa_skillopt") == config
