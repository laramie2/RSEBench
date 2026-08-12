"""Stable data contracts shared by benchmark construction and evaluation."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Channel(str, Enum):
    task_communication = "C1"
    evidence_artifact = "C2"
    interaction_observation = "C3"
    feedback_selection = "C4"


class Mechanism(str, Enum):
    addition = "M1"
    distortion = "M2"
    omission = "M3"
    duplication_staleness = "M4"
    reordering_access = "M5"
    instability = "M6"


class SeverityLevel(str, Enum):
    clean = "L0"
    low = "L1"
    medium = "L2"
    high = "L3"


class NoiseTiming(str, Enum):
    evolution = "evolution"
    test = "test"


class GeneratorMode(str, Enum):
    rule = "rule"
    model = "model"
    hybrid = "hybrid"


class Severity(StrictModel):
    level: SeverityLevel
    budget: int = Field(default=1, ge=0)
    semantic_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class TaskManifest(StrictModel):
    task_id: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    gold_answers: list[str] = Field(min_length=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_path: str | None = None
    verifier: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NoiseManifest(StrictModel):
    noise_id: str = Field(min_length=1)
    channel: Channel
    mechanism: Mechanism
    operator: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    severity: Severity
    seed: int
    clean_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str | None = None
    noisy_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generator_mode: GeneratorMode = GeneratorMode.rule
    timing: NoiseTiming = NoiseTiming.test
    template_version: str = "v1"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(StrictModel):
    structural_valid: bool
    label_invariant: bool
    solvable: bool
    answer_leak_free: bool
    accepted: bool
    applicable: bool = True
    checks: dict[str, bool | int | float | str] = Field(default_factory=dict)
    messages: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def accepted_requires_hard_gates(self) -> "ValidationReport":
        gates = (
            self.structural_valid,
            self.label_invariant,
            self.solvable,
            self.answer_leak_free,
            self.applicable,
        )
        if self.accepted and not all(gates):
            raise ValueError("accepted noise requires all hard gates to pass")
        return self
