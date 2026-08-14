"""Immutable manifests for paired self-evolution experiments."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from rsebench.contracts import NoiseManifest, StrictModel, TaskManifest


Hash = str


class EvolutionTaskPair(StrictModel):
    pair_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    clean: TaskManifest
    noisy: TaskManifest
    noise: NoiseManifest

    @model_validator(mode="after")
    def validate_pair(self) -> "EvolutionTaskPair":
        if {self.task_id, self.clean.task_id, self.noisy.task_id} != {self.task_id}:
            raise ValueError("paired task IDs must match")
        if (
            self.clean.benchmark != self.noisy.benchmark
            or self.clean.domain != self.noisy.domain
        ):
            raise ValueError("paired benchmark and domain must match")
        if (
            self.clean.gold_answers != self.noisy.gold_answers
            or self.clean.verifier != self.noisy.verifier
        ):
            raise ValueError("paired labels or verifier must be invariant")
        if self.noise.task_id != self.task_id:
            raise ValueError("noise task_id must match pair task_id")
        if self.noise.timing.value != "evolution":
            raise ValueError("paired noise timing must be evolution")
        if self.noise.clean_hash != self.clean.source_hash:
            raise ValueError("noise clean_hash must match clean payload")
        if self.noise.noisy_hash != self.noisy.source_hash:
            raise ValueError("noise noisy_hash must match noisy payload")
        return self


class EvolutionSplitManifest(StrictModel):
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    seed: int
    source_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    train: list[EvolutionTaskPair]
    validation: list[EvolutionTaskPair]
    clean_test: list[TaskManifest]

    @model_validator(mode="after")
    def validate_isolation(self) -> "EvolutionSplitManifest":
        train_ids = [pair.task_id for pair in self.train]
        validation_ids = [pair.task_id for pair in self.validation]
        test_ids = [task.task_id for task in self.clean_test]
        all_ids = train_ids + validation_ids + test_ids
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("train, validation, and clean_test task IDs must be disjoint")
        for pair in self.train + self.validation:
            if pair.clean.benchmark != self.benchmark or pair.clean.domain != self.domain:
                raise ValueError("pair benchmark/domain does not match split")
        for task in self.clean_test:
            if task.benchmark != self.benchmark or task.domain != self.domain:
                raise ValueError("clean_test benchmark/domain does not match split")
        return self


class ArmTaskRef(StrictModel):
    pair_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    payload_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    noise_id: str | None = None


class EvolutionArmManifest(StrictModel):
    arm: Literal["clean", "noisy"]
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    method: str = Field(min_length=1)
    method_seed: int
    split_seed: int
    split_source_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    seed_skill_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    train: list[ArmTaskRef]
    validation: list[ArmTaskRef]
    clean_test: list[ArmTaskRef]
    parameters: dict[str, Any] = Field(default_factory=dict)
