import hashlib

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_bridge import build_clean_runtime_split
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.evolution.pairs import build_clean_arm_manifest


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="document",
        prompt=f"clean {task_id}",
        gold_answers=["x"],
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
    )


def test_clean_bridge_builds_only_a_clean_arm() -> None:
    clean = CleanEvolutionSplitManifest(
        benchmark="fixture",
        domain="document",
        seed=7,
        source_hash="a" * 64,
        train=[_task("train")],
        validation=[_task("validation")],
        clean_test=[_task("test")],
    )
    runtime = build_clean_runtime_split(clean)
    arm = build_clean_arm_manifest(
        runtime,
        method="fixture",
        method_seed=11,
        seed_skill_hash="b" * 64,
        parameters={"qualification_version": "v1"},
    )

    assert arm.arm == "clean"
    assert arm.train[0].noise_id is None
    assert runtime.train[0].clean == runtime.train[0].noisy
    assert runtime.train[0].noise.operator == "clean_qualification_identity"
