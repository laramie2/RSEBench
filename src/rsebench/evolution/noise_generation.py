"""Hard-gated assembly of accepted evolution-time noise pairs."""

from __future__ import annotations

from pydantic import Field, model_validator

from rsebench.contracts import NoiseManifest, StrictModel, TaskManifest, ValidationReport
from rsebench.evolution.contracts import EvolutionTaskPair
from rsebench.evolution.splits import build_evolution_split


class PairGenerationError(RuntimeError):
    pass


class PairedNoiseRecord(StrictModel):
    task_id: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    clean: TaskManifest
    noisy: TaskManifest
    noise: NoiseManifest
    validation: ValidationReport
    artifact_path: str | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def identity(self) -> "PairedNoiseRecord":
        if self.task_id not in {self.clean.task_id, self.noisy.task_id} or (
            self.clean.task_id != self.noisy.task_id
        ):
            raise ValueError("paired noise record task IDs must match")
        return self


def assemble_evolution_split(
    *,
    benchmark: str,
    domain: str,
    seed: int,
    source_hash: str,
    records: list[PairedNoiseRecord],
    train_ids: list[str],
    validation_ids: list[str],
    clean_test: list[TaskManifest],
):
    test_ids = {task.task_id for task in clean_test}
    record_ids = {record.task_id for record in records}
    if test_ids & record_ids:
        raise PairGenerationError("clean_test IDs must never appear in noisy records")
    requested = train_ids + validation_ids
    if len(requested) != len(set(requested)):
        raise PairGenerationError("train and validation IDs must be disjoint")
    by_id = {record.task_id: record for record in records}
    missing = [task_id for task_id in requested if task_id not in by_id]
    if missing:
        raise PairGenerationError(f"missing noise records for task IDs: {missing}")
    rejected = [
        task_id for task_id in requested if not by_id[task_id].validation.accepted
    ]
    if rejected:
        raise PairGenerationError(
            f"noise failed hard gates for task IDs: {rejected}"
        )

    def pair(task_id: str) -> EvolutionTaskPair:
        record = by_id[task_id]
        if record.noise.timing.value != "evolution":
            raise PairGenerationError(
                f"noise timing is not evolution for task ID: {task_id}"
            )
        return EvolutionTaskPair(
            pair_id=f"{record.noise.noise_id}--pair",
            task_id=task_id,
            clean=record.clean,
            noisy=record.noisy,
            noise=record.noise,
        )

    return build_evolution_split(
        benchmark=benchmark,
        domain=domain,
        seed=seed,
        source_hash=source_hash,
        train=[pair(task_id) for task_id in train_ids],
        validation=[pair(task_id) for task_id in validation_ids],
        clean_test=clean_test,
    )
