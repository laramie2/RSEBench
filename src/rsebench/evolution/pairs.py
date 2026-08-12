"""Build and compare paired clean/noisy experiment arms."""

from __future__ import annotations

from rsebench.evolution.contracts import (
    ArmTaskRef,
    EvolutionArmManifest,
    EvolutionSplitManifest,
    EvolutionTaskPair,
)


def _pair_refs(
    pairs: list[EvolutionTaskPair], arm: str
) -> list[ArmTaskRef]:
    refs: list[ArmTaskRef] = []
    for pair in pairs:
        task = pair.clean if arm == "clean" else pair.noisy
        refs.append(
            ArmTaskRef(
                pair_id=pair.pair_id,
                task_id=pair.task_id,
                payload_hash=task.source_hash,
                noise_id=pair.noise.noise_id if arm == "noisy" else None,
            )
        )
    return refs


def build_arm_manifests(
    split: EvolutionSplitManifest,
    *,
    method: str,
    method_seed: int,
    seed_skill_hash: str,
    parameters: dict | None = None,
) -> tuple[EvolutionArmManifest, EvolutionArmManifest]:
    shared = {
        "benchmark": split.benchmark,
        "domain": split.domain,
        "method": method,
        "method_seed": method_seed,
        "split_seed": split.seed,
        "split_source_hash": split.source_hash,
        "seed_skill_hash": seed_skill_hash,
        "parameters": dict(parameters or {}),
        "clean_test": [
            ArmTaskRef(
                pair_id=f"clean-test-{task.task_id}",
                task_id=task.task_id,
                payload_hash=task.source_hash,
            )
            for task in split.clean_test
        ],
    }
    clean = EvolutionArmManifest(
        arm="clean",
        train=_pair_refs(split.train, "clean"),
        validation=_pair_refs(split.validation, "clean"),
        **shared,
    )
    noisy = EvolutionArmManifest(
        arm="noisy",
        train=_pair_refs(split.train, "noisy"),
        validation=_pair_refs(split.validation, "noisy"),
        **shared,
    )
    assert_arm_equivalence(clean, noisy)
    return clean, noisy


def assert_arm_equivalence(
    clean: EvolutionArmManifest, noisy: EvolutionArmManifest
) -> None:
    """Reject any arm difference beyond evolution payload/noise references."""
    if clean.arm != "clean" or noisy.arm != "noisy":
        raise ValueError("expected clean and noisy arms")
    for field in (
        "benchmark",
        "domain",
        "method",
        "method_seed",
        "split_seed",
        "split_source_hash",
        "seed_skill_hash",
        "parameters",
    ):
        if getattr(clean, field) != getattr(noisy, field):
            raise ValueError(f"arm mismatch: {field}")
    if clean.clean_test != noisy.clean_test:
        raise ValueError("arm mismatch: clean_test")
    for split_name in ("train", "validation"):
        clean_refs = getattr(clean, split_name)
        noisy_refs = getattr(noisy, split_name)
        if len(clean_refs) != len(noisy_refs):
            raise ValueError(f"arm mismatch: {split_name} length")
        for left, right in zip(clean_refs, noisy_refs, strict=True):
            if (left.pair_id, left.task_id) != (right.pair_id, right.task_id):
                raise ValueError(f"arm mismatch: {split_name} identity")
            if left.noise_id is not None or right.noise_id is None:
                raise ValueError(f"arm mismatch: {split_name} noise mapping")
