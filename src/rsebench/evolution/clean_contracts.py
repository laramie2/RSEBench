"""Data contracts for clean-only self-evolution qualification."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel, TaskManifest


class CleanEvolutionSplitManifest(StrictModel):
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    seed: int
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    train: list[TaskManifest]
    validation: list[TaskManifest]
    clean_test: list[TaskManifest]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_isolation(self) -> "CleanEvolutionSplitManifest":
        ids = {
            "train": [task.task_id for task in self.train],
            "validation": [task.task_id for task in self.validation],
            "clean_test": [task.task_id for task in self.clean_test],
        }
        flattened = ids["train"] + ids["validation"] + ids["clean_test"]
        if len(flattened) != len(set(flattened)):
            raise ValueError(
                "train, validation, and clean_test task IDs must be disjoint"
            )
        for task in self.train + self.validation + self.clean_test:
            if task.benchmark != self.benchmark or task.domain != self.domain:
                raise ValueError("task benchmark/domain does not match clean split")
        validation_only = (
            self.benchmark == "skilllearnbench"
            and self.domain == "skill_learning"
            and self.metadata.get("qualification_version") == "noise-screen-v1"
            and self.metadata.get("evaluation_mode") == "validation_only"
        )
        if not self.train or not self.validation:
            raise ValueError("clean qualification requires non-empty train and validation")
        if not self.clean_test and not validation_only:
            raise ValueError("clean qualification requires non-empty clean_test")
        return self


class EvolutionExecutionAudit(StrictModel):
    train_task_ids: list[str]
    validation_task_ids: list[str]
    accepted_update_count: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "EvolutionExecutionAudit":
        for name, values in (
            ("train", self.train_task_ids),
            ("validation", self.validation_task_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name} task IDs in execution audit")
        return self


class CleanQualificationPolicy(StrictModel):
    min_parseable_answer_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    max_systemic_failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class CleanQualificationDecision(StrictModel):
    execution_coverage_passed: bool
    artifact_updated: bool
    accepted_update_count: int = Field(ge=0)
    nondegrading: bool
    runtime_gates_passed: bool
    seed_score: float
    evolved_score: float
    clean_gain: float
    strictly_positive_gain: bool
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)
