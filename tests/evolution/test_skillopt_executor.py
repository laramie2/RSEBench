import json
from pathlib import Path
from types import SimpleNamespace

from rsebench.contracts import TaskManifest
from rsebench.evolution.contracts import ArmTaskRef, EvolutionArmManifest
from rsebench.evolution.skillopt_executor import SkillOptBudget, SkillOptExecutor


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


def test_skillopt_executor_runs_native_train_and_parses_eval(tmp_path: Path):
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

    def fake_run(command, **kwargs):
        commands.append(command)
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
        output_dir=tmp_path / "arm",
    )
    evaluation = executor.evaluate(
        skill_path=Path(artifact.skill_path),
        clean_test=split.clean_test,
        output_dir=tmp_path / "eval",
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
    assert all(any("openai_compatible" in arg for arg in command) for command in commands)
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "arm").rglob("*")
        if path.is_file()
    )
    assert "must-not-be-written" not in persisted


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

    assert f"env.data_dirs={corpus},{parsed}" in executor._domain_options(
        "officeqa_full"
    )


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
