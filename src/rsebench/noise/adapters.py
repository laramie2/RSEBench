"""Compatibility bridges for existing static and evidence-noise implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from rsebench.contracts import TaskManifest
from rsebench.evidence import (
    EvidenceStage,
    FeedbackRecord,
    MutationResult,
    RuntimeNoiseSpec,
    TrajectoryRecord,
    mutate_record,
    write_record,
)
from rsebench.noise.base import NoiseOperator
from rsebench.noise.contracts import StaticNoiseResult, StaticNoiseSpec


class LegacyGeneratedNoiseAdapter:
    """Expose the original GeneratedNoise API through the N1/N2 contract."""

    def __init__(
        self,
        *,
        stage: Literal["N1", "N2"],
        operator: NoiseOperator,
        version: str,
    ) -> None:
        self.stage = stage
        self.operator = operator
        self.version = version

    def materialize(
        self,
        task: TaskManifest,
        spec: StaticNoiseSpec,
        output_dir: Path,
    ) -> StaticNoiseResult:
        if spec.stage != self.stage:
            raise ValueError(
                f"static adapter stage differs: {self.stage} != {spec.stage}"
            )
        generated = self.operator.generate(
            task,
            spec.severity,
            spec.seed,
            timing="evolution",
        )
        destination = output_dir / "noisy.json"
        write_record(destination, generated.payload)
        checks = {
            "structural_valid": generated.validation.structural_valid,
            "label_invariant": generated.validation.label_invariant,
            "solvable": generated.validation.solvable,
            "answer_leak_free": generated.validation.answer_leak_free,
        }
        return StaticNoiseResult(
            stage=self.stage,
            operator=generated.manifest.operator,
            version=self.version,
            task_id=task.task_id,
            seed=spec.seed,
            applicable=generated.validation.accepted,
            clean_hash=generated.manifest.clean_hash,
            noisy_hash=generated.manifest.noisy_hash or generated.manifest.clean_hash,
            noisy_uri=f"rsebench-attempt://{task.task_id}/noisy.json",
            protected_field_audit=checks,
            changes=("materialized legacy GeneratedNoise payload",),
            reason=(None if generated.validation.accepted else "legacy hard gate failed"),
        )


class RuntimeMutationOperator:
    """Expose the existing deterministic N3/N4 mutator without behavior changes."""

    def __init__(self, *, stage: Literal["N3", "N4"]) -> None:
        self.stage = stage

    def mutate(
        self,
        record: TrajectoryRecord | FeedbackRecord,
        spec: RuntimeNoiseSpec,
        *,
        trajectory: TrajectoryRecord | None = None,
    ) -> MutationResult:
        expected = EvidenceStage(self.stage)
        if spec.stage != expected:
            raise ValueError(
                f"runtime adapter stage differs: {self.stage} != {spec.stage.value}"
            )
        return mutate_record(record, spec, trajectory=trajectory)


__all__ = ["LegacyGeneratedNoiseAdapter", "RuntimeMutationOperator"]
