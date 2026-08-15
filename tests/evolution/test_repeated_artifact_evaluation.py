import json
from pathlib import Path

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution import artifact_evaluation
from rsebench.evolution.runner import EvaluationResult


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        prompt=f"task {task_id}",
        gold_answers=["ok"],
        source_hash=(task_id.encode().hex() + "0" * 64)[:64],
    )


class _ReplayExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Path]] = []
        self.token_root: Path | None = None
        self.timing = None

    def configure_token_run(self, output_dir: Path) -> None:
        self.token_root = output_dir

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
        output_dir.mkdir(parents=True)
        self.calls.append((skill_path.stem, stage, output_dir))
        assert self.timing is not None
        for task in clean_test:
            with self.timing.span(
                level="task", name=stage, task_id=task.task_id
            ):
                pass
        repeat = int(stage.rsplit("_r", maxsplit=1)[1])
        if skill_path.stem == "seed":
            scores = {"t1": 1.0, "t2": 0.0 if repeat != 2 else 1.0}
        else:
            scores = {"t1": 1.0, "t2": 1.0 if repeat != 2 else 0.0}
        return EvaluationResult(
            score=sum(scores.values()) / len(scores),
            per_task_scores=scores,
            diagnostics={"stage": stage},
        )


def test_repeated_artifact_evaluation_records_isolated_repeats_and_deltas(
    tmp_path: Path,
) -> None:
    replay = getattr(artifact_evaluation, "evaluate_repeated_artifacts", None)
    assert callable(replay), "repeated fixed-artifact evaluator is missing"

    seed = tmp_path / "seed.md"
    candidate = tmp_path / "candidate.md"
    seed.write_text("seed\n", encoding="utf-8")
    candidate.write_text("candidate\n", encoding="utf-8")
    executor = _ReplayExecutor()

    result = replay(
        executor=executor,
        artifacts={"seed": seed, "candidate": candidate},
        reference_label="seed",
        clean_test=[_task("t1"), _task("t2")],
        repeats=3,
        output_dir=tmp_path / "replay",
    )

    assert executor.token_root == (tmp_path / "replay").resolve()
    assert [(name, stage) for name, stage, _ in executor.calls] == [
        ("seed", "replay_seed_r1"),
        ("candidate", "replay_candidate_r1"),
        ("candidate", "replay_candidate_r2"),
        ("seed", "replay_seed_r2"),
        ("seed", "replay_seed_r3"),
        ("candidate", "replay_candidate_r3"),
    ]
    assert result.repeat_count == 3
    assert result.order_policy == "cyclic_rotation"
    assert result.reference_label == "seed"
    assert result.summaries["seed"].scores == [0.5, 1.0, 0.5]
    assert result.summaries["candidate"].scores == [1.0, 0.5, 1.0]
    assert result.summaries["candidate"].deltas_vs_reference == [0.5, -0.5, 0.5]
    assert result.summaries["candidate"].mean_delta_vs_reference == pytest.approx(
        1 / 6
    )
    assert len({path for _, _, path in executor.calls}) == 6
    assert result.timing.run.name == "fixed_artifact_replay"
    assert len(result.timing.stages) == 6
    assert len(result.timing.tasks) == 12
    assert {span.task_id for span in result.timing.tasks} == {"t1", "t2"}
    assert result.token_usage["attempted_calls"] == 0

    persisted = json.loads((tmp_path / "replay/result.json").read_text())
    assert persisted["schema_version"] == "rsebench.fixed-artifact-replay.v1"
    assert persisted["artifact_hashes"] == result.artifact_hashes
    assert persisted["timing"]["run"]["level"] == "run"
    assert (tmp_path / "replay/timing/events.jsonl").is_file()
    assert (tmp_path / "replay/timing/summary.json").is_file()


def test_repeated_artifact_evaluation_resumes_only_missing_repeats(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed.md"
    candidate = tmp_path / "candidate.md"
    seed.write_text("seed\n", encoding="utf-8")
    candidate.write_text("candidate\n", encoding="utf-8")
    output_dir = tmp_path / "replay"
    artifacts = {"seed": seed, "candidate": candidate}
    tasks = [_task("t1"), _task("t2")]

    initial_executor = _ReplayExecutor()
    artifact_evaluation.evaluate_repeated_artifacts(
        executor=initial_executor,
        artifacts=artifacts,
        reference_label="seed",
        clean_test=tasks,
        repeats=2,
        output_dir=output_dir,
    )

    resumed_executor = _ReplayExecutor()
    result = artifact_evaluation.evaluate_repeated_artifacts(
        executor=resumed_executor,
        artifacts=artifacts,
        reference_label="seed",
        clean_test=tasks,
        repeats=4,
        output_dir=output_dir,
        resume=True,
    )

    assert [(name, stage) for name, stage, _ in resumed_executor.calls] == [
        ("seed", "replay_seed_r3"),
        ("candidate", "replay_candidate_r3"),
        ("candidate", "replay_candidate_r4"),
        ("seed", "replay_seed_r4"),
    ]
    assert result.repeat_count == 4
    assert result.artifact_order == ["seed", "candidate"]
    assert len(result.observations) == 8
    assert len(result.summaries["seed"].scores) == 4
    assert result.resume_history[-1].from_repeat_count == 2
    assert result.resume_history[-1].to_repeat_count == 4
    assert len(result.timing.stages) == 8
    assert len(result.timing.tasks) == 16


def test_repeated_artifact_evaluation_resume_rejects_changed_artifact(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed.md"
    candidate = tmp_path / "candidate.md"
    seed.write_text("seed\n", encoding="utf-8")
    candidate.write_text("candidate\n", encoding="utf-8")
    output_dir = tmp_path / "replay"
    artifacts = {"seed": seed, "candidate": candidate}
    tasks = [_task("t1"), _task("t2")]
    artifact_evaluation.evaluate_repeated_artifacts(
        executor=_ReplayExecutor(),
        artifacts=artifacts,
        reference_label="seed",
        clean_test=tasks,
        repeats=2,
        output_dir=output_dir,
    )
    candidate.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hashes"):
        artifact_evaluation.evaluate_repeated_artifacts(
            executor=_ReplayExecutor(),
            artifacts=artifacts,
            reference_label="seed",
            clean_test=tasks,
            repeats=3,
            output_dir=output_dir,
            resume=True,
        )
