"""Common protocol and output type for all noise operators."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from rsebench.contracts import NoiseManifest, TaskManifest, ValidationReport


class GeneratedNoise(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    manifest: NoiseManifest
    payload: dict[str, Any]
    validation: ValidationReport


class NoiseOperator(Protocol):
    def generate(
        self,
        task: TaskManifest,
        severity: str,
        seed: int,
        *,
        timing: str = "test",
    ) -> GeneratedNoise: ...
