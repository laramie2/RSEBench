"""In-memory bridge from clean-only manifests to existing executor contracts."""

from __future__ import annotations

from rsebench.contracts import NoiseManifest, Severity, TaskManifest
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.evolution.contracts import EvolutionSplitManifest, EvolutionTaskPair


def _identity_pair(task: TaskManifest, *, seed: int) -> EvolutionTaskPair:
    pair_id = f"clean-qualification:{task.benchmark}:{task.task_id}"
    return EvolutionTaskPair(
        pair_id=pair_id,
        task_id=task.task_id,
        clean=task,
        noisy=task,
        noise=NoiseManifest(
            noise_id=f"{pair_id}:identity",
            task_id=task.task_id,
            channel="C1",
            mechanism="M1",
            operator="clean_qualification_identity",
            domain=task.domain,
            benchmark=task.benchmark,
            severity=Severity(level="L0", budget=0),
            seed=seed,
            clean_hash=task.source_hash,
            noisy_hash=task.source_hash,
            timing="evolution",
            metadata={"transient": True},
        ),
    )


def build_clean_runtime_split(
    split: CleanEvolutionSplitManifest,
) -> EvolutionSplitManifest:
    """Build the paired-shaped transient view required by current executors."""

    return EvolutionSplitManifest(
        benchmark=split.benchmark,
        domain=split.domain,
        seed=split.seed,
        source_hash=split.source_hash,
        train=[_identity_pair(task, seed=split.seed) for task in split.train],
        validation=[
            _identity_pair(task, seed=split.seed) for task in split.validation
        ],
        clean_test=list(split.clean_test),
    )
