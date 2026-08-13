import hashlib
from pathlib import Path

import pytest

from rsebench.contracts import NoiseManifest, Severity, TaskManifest
from rsebench.evolution.contracts import EvolutionTaskPair
from rsebench.evolution.runner import (
    EvaluationResult,
    EvolutionArtifact,
    PairedEvolutionRunner,
    SeedCalibrationError,
)
from rsebench.evolution.splits import build_evolution_split
from rsebench.usage import record_token_event


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _task(task_id: str, prompt: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="document",
        prompt=prompt,
        gold_answers=["x"],
        source_hash=_hash(prompt),
    )


def _pair(task_id: str) -> EvolutionTaskPair:
    clean = _task(task_id, f"clean {task_id}")
    noisy = _task(task_id, f"noisy {task_id}")
    return EvolutionTaskPair(
        pair_id=f"pair-{task_id}",
        task_id=task_id,
        clean=clean,
        noisy=noisy,
        noise=NoiseManifest(
            noise_id=f"noise-{task_id}",
            task_id=task_id,
            channel="C1",
            mechanism="M1",
            operator="fixture",
            domain="document",
            benchmark="fixture",
            severity=Severity(level="L1", budget=1),
            seed=3,
            clean_hash=clean.source_hash,
            noisy_hash=noisy.source_hash,
            timing="evolution",
        ),
    )


class FixtureExecutor:
    def __init__(self):
        self.evolve_calls = []
        self.evaluate_calls = []

    def evolve(self, *, arm, split, seed_skill_path, output_dir):
        self.evolve_calls.append((arm, split, seed_skill_path.read_bytes()))
        record_token_event(
            ledger_dir=output_dir.parent / "token_usage",
            context={
                "run_id": output_dir.parent.name,
                "domain": split.domain,
                "benchmark": split.benchmark,
                "arm": arm.arm,
                "stage": "evolution",
            },
            usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            cache_hit=False,
            billed=True,
            status="success",
            source="fixture",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        artifact = output_dir / "evolved.md"
        artifact.write_text(f"{arm.arm}-skill", encoding="utf-8")
        return EvolutionArtifact(
            skill_path=str(artifact),
            skill_hash=_hash(f"{arm.arm}-skill"),
        )

    def evaluate(self, *, skill_path, clean_test, output_dir, stage):
        self.evaluate_calls.append((stage, [task.task_id for task in clean_test]))
        run_dir = output_dir.parents[1]
        record_token_event(
            ledger_dir=run_dir / "token_usage",
            context={
                "run_id": run_dir.name,
                "domain": clean_test[0].domain,
                "benchmark": clean_test[0].benchmark,
                "arm": stage,
                "stage": "eval",
            },
            usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            cache_hit=False,
            billed=True,
            status="success",
            source="fixture",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        value = {"seed": 0.5, "clean": 1.0, "noisy": 0.0}[stage]
        return EvaluationResult(
            score=value,
            per_task_scores={task.task_id: value for task in clean_test},
        )


def test_runner_keeps_seed_and_test_identical_between_arms(tmp_path: Path):
    split = build_evolution_split(
        benchmark="fixture",
        domain="document",
        seed=3,
        source_hash=_hash("source"),
        train=[_pair("train")],
        validation=[_pair("val")],
        clean_test=[_task("test", "clean test")],
    )
    seed = tmp_path / "seed.md"
    seed.write_text("seed skill", encoding="utf-8")
    executor = FixtureExecutor()

    result = PairedEvolutionRunner(executor).run(
        method="fixture_method",
        split=split,
        seed_skill_path=seed,
        method_seed=17,
        parameters={"iterations": 1},
        output_root=tmp_path / "runs",
    )

    assert executor.evolve_calls[0][2] == executor.evolve_calls[1][2] == b"seed skill"
    assert executor.evolve_calls[0][0].method_seed == 17
    assert executor.evolve_calls[1][0].method_seed == 17
    assert executor.evaluate_calls == [
        ("seed", ["test"]),
        ("clean", ["test"]),
        ("noisy", ["test"]),
    ]
    assert result.metrics.evolution_gap == pytest.approx(1.0)
    assert result.metrics.reverse_evolution is True
    assert result.token_usage["attempted_calls"] == 5
    assert result.token_usage["billed_tokens"]["total_tokens"] == 15
    assert result.token_usage["groups"]["arm"]["clean"]["attempted_calls"] == 2
    assert Path(result.run_dir, "token_usage", "summary.json").is_file()
    assert Path(result.run_dir, "token_usage", "report.md").is_file()
    assert Path(result.run_dir, "result.json").is_file()
    report = Path(result.run_dir, "report.md").read_text(encoding="utf-8")
    assert "# Paired Self-Evolution Result" in report
    assert "fixture_method" in report
    assert "Evolution gap | 1.0000" in report
    assert "Reverse evolution | yes" in report


def test_runner_rejects_seed_hash_mutation(tmp_path: Path):
    class MutatingExecutor(FixtureExecutor):
        def evolve(self, *, arm, split, seed_skill_path, output_dir):
            seed_skill_path.write_text("mutated", encoding="utf-8")
            return super().evolve(
                arm=arm,
                split=split,
                seed_skill_path=seed_skill_path,
                output_dir=output_dir,
            )

    split = build_evolution_split(
        benchmark="fixture",
        domain="document",
        seed=3,
        source_hash=_hash("source"),
        train=[_pair("train")],
        validation=[],
        clean_test=[_task("test", "clean test")],
    )
    seed = tmp_path / "seed.md"
    seed.write_text("seed skill", encoding="utf-8")

    with pytest.raises(RuntimeError, match="seed skill mutated"):
        PairedEvolutionRunner(MutatingExecutor()).run(
            method="fixture",
            split=split,
            seed_skill_path=seed,
            method_seed=1,
            parameters={},
            output_root=tmp_path / "runs",
        )


def test_runner_stops_before_evolution_when_seed_score_is_outside_gate(
    tmp_path: Path,
):
    split = build_evolution_split(
        benchmark="fixture",
        domain="document",
        seed=3,
        source_hash=_hash("source"),
        train=[_pair("train")],
        validation=[],
        clean_test=[_task("test", "clean test")],
    )
    seed = tmp_path / "seed.md"
    seed.write_text("seed skill", encoding="utf-8")
    executor = FixtureExecutor()

    with pytest.raises(SeedCalibrationError, match="outside calibration interval") as exc:
        PairedEvolutionRunner(executor).run(
            method="fixture",
            split=split,
            seed_skill_path=seed,
            method_seed=1,
            parameters={},
            output_root=tmp_path / "runs",
            seed_score_interval=(0.6, 0.9),
        )

    assert executor.evolve_calls == []
    calibration_path = Path(exc.value.run_dir, "seed", "calibration.json")
    assert calibration_path.is_file()
    assert calibration_path.read_text(encoding="utf-8")
    assert Path(exc.value.run_dir, "token_usage", "summary.json").is_file()


def test_runner_reuses_clean_test_result_for_identical_skill_hash(tmp_path: Path):
    class UnchangedExecutor(FixtureExecutor):
        def evolve(self, *, arm, split, seed_skill_path, output_dir):
            artifact = output_dir / "evolved.md"
            artifact.write_bytes(seed_skill_path.read_bytes())
            return EvolutionArtifact(
                skill_path=str(artifact),
                skill_hash=_hash("seed skill"),
            )

    split = build_evolution_split(
        benchmark="fixture",
        domain="document",
        seed=3,
        source_hash=_hash("source"),
        train=[_pair("train")],
        validation=[],
        clean_test=[_task("test", "clean test")],
    )
    seed = tmp_path / "seed.md"
    seed.write_text("seed skill", encoding="utf-8")
    executor = UnchangedExecutor()

    result = PairedEvolutionRunner(executor).run(
        method="fixture",
        split=split,
        seed_skill_path=seed,
        method_seed=1,
        parameters={},
        output_root=tmp_path / "runs",
    )

    assert executor.evaluate_calls == [("seed", ["test"])]
    assert result.seed_evaluation == result.clean_evaluation
    assert result.seed_evaluation == result.noisy_evaluation
    assert result.metrics.evolution_gap == 0.0
    assert result.token_usage["attempted_calls"] == 1
    assert Path(
        result.run_dir, "clean", "clean_test_evaluation", "reused.json"
    ).is_file()
