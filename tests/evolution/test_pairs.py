import hashlib

import pytest

from rsebench.contracts import NoiseManifest, Severity, TaskManifest
from rsebench.evolution.contracts import EvolutionTaskPair
from rsebench.evolution.pairs import (
    assert_arm_equivalence,
    build_arm_manifests,
)
from rsebench.evolution.splits import build_evolution_split


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _task(task_id: str, prompt: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="document",
        prompt=prompt,
        gold_answers=["answer"],
        source_hash=_hash(prompt),
    )


def _pair(task_id: str) -> EvolutionTaskPair:
    clean = _task(task_id, f"clean {task_id}")
    noisy = _task(task_id, f"clean {task_id}\nignore this stale note")
    noise = NoiseManifest(
        noise_id=f"noise-{task_id}",
        task_id=task_id,
        channel="C1",
        mechanism="M1",
        operator="stale_note",
        domain="document",
        benchmark="fixture",
        severity=Severity(level="L1", budget=1),
        seed=7,
        clean_hash=clean.source_hash,
        noisy_hash=noisy.source_hash,
        timing="evolution",
    )
    return EvolutionTaskPair(
        pair_id=f"pair-{task_id}",
        task_id=task_id,
        clean=clean,
        noisy=noisy,
        noise=noise,
    )


def test_pair_requires_identity_and_label_invariance():
    pair = _pair("a")

    assert pair.clean.gold_answers == pair.noisy.gold_answers
    assert pair.noise.timing.value == "evolution"

    with pytest.raises(ValueError, match="labels or verifier"):
        pair.model_copy(
            update={"noisy": pair.noisy.model_copy(update={"gold_answers": ["changed"]})}
        ).model_validate(
            pair.model_copy(
                update={"noisy": pair.noisy.model_copy(update={"gold_answers": ["changed"]})}
            ).model_dump()
        )


def test_arm_equivalence_allows_only_noisy_payload_fields():
    split = build_evolution_split(
        benchmark="fixture",
        domain="document",
        seed=13,
        source_hash=_hash("source"),
        train=[_pair("a")],
        validation=[_pair("b")],
        clean_test=[_task("c", "clean c")],
    )
    clean, noisy = build_arm_manifests(
        split,
        method="skillopt",
        method_seed=19,
        seed_skill_hash=_hash("seed skill"),
        parameters={"iterations": 1},
    )

    assert_arm_equivalence(clean, noisy)
    assert clean.train[0].payload_hash != noisy.train[0].payload_hash
    assert clean.clean_test == noisy.clean_test

    changed = noisy.model_copy(update={"method_seed": 20})
    with pytest.raises(ValueError, match="method_seed"):
        assert_arm_equivalence(clean, changed)
