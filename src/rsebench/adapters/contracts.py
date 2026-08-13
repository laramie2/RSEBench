"""Strict schemas for baseline API adaptation and smoke evidence."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SmokeLevel(str, Enum):
    transport = "transport"
    structured = "structured"
    tool = "tool"
    native_task = "native_task"
    evolution = "evolution"


SMOKE_LEVELS = tuple(SmokeLevel)


class BaselineAdapterSpec(StrictModel):
    name: str = Field(min_length=1)
    upstream_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    method_path: str = Field(min_length=1)
    launcher: str = Field(min_length=1)
    model: str
    roles: list[str] = Field(min_length=1)
    native_domains: list[str] = Field(min_length=1)
    active: bool = False

    @model_validator(mode="after")
    def locked_model(self) -> "BaselineAdapterSpec":
        if self.model != "deepseek-v4-flash":
            raise ValueError("baseline adapter model must be deepseek-v4-flash")
        return self


class AdapterRegistry(StrictModel):
    version: int = 1
    adapters: dict[str, BaselineAdapterSpec]


class SmokeLevelRecord(StrictModel):
    level: SmokeLevel
    status: Literal["passed", "failed", "blocked"]
    detail: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class SmokeRunRecord(StrictModel):
    method: str
    model: str
    through: SmokeLevel
    status: Literal["passed", "failed", "blocked"]
    run_dir: str
    levels: list[SmokeLevelRecord] = Field(default_factory=list)
