"""Strict profiles for the four-domain Core-1 validation benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel
from rsebench.registry import load_registry


class Core1OperatorProfile(StrictModel):
    operator_id: str = Field(min_length=1)
    stage: str = Field(pattern=r"^N[1-4]$")
    channel: str = Field(pattern=r"^C[1-4]$")
    mechanism: str = Field(pattern=r"^M[1-6]$")
    modes: list[str] = Field(min_length=1)


class Core1Profile(StrictModel):
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    primary_method: str = Field(min_length=1)
    operators: dict[str, Core1OperatorProfile]
    source: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_all_stages(self) -> "Core1Profile":
        if set(self.operators) != {"N1", "N2", "N3", "N4"}:
            raise ValueError("Core-1 profile requires exactly N1, N2, N3, and N4")
        if any(key != value.stage for key, value in self.operators.items()):
            raise ValueError("Core-1 operator key must match its stage")
        return self


def load_core1_profiles(registry_root: str | Path) -> dict[str, Core1Profile]:
    root = Path(registry_root)
    benchmarks = load_registry(root / "benchmarks.yaml")["benchmarks"]
    methods = load_registry(root / "methods.yaml")["methods"]
    operators = load_registry(root / "noise_operators.yaml")["operators"]
    profiles: dict[str, Core1Profile] = {}
    for benchmark, row in benchmarks.items():
        if not row.get("active") or row.get("tier") != "core1":
            continue
        primary_method = row.get("primary_method")
        if primary_method not in methods:
            raise ValueError(
                f"Core-1 benchmark {benchmark} references unknown method "
                f"{primary_method}"
            )
        stage_map = row.get("operators", {})
        resolved: dict[str, Core1OperatorProfile] = {}
        for stage, operator_id in stage_map.items():
            if operator_id not in operators:
                raise ValueError(
                    f"Core-1 benchmark {benchmark} references unknown operator "
                    f"{operator_id}"
                )
            operator = operators[operator_id]
            if not operator.get("active"):
                raise ValueError(f"Core-1 operator {operator_id} is inactive")
            if row["domain"] not in operator.get("domains", []):
                raise ValueError(
                    f"Core-1 operator {operator_id} does not support {row['domain']}"
                )
            resolved[stage] = Core1OperatorProfile(
                operator_id=operator_id,
                stage=operator["stage"],
                channel=operator["channel"],
                mechanism=operator["mechanism"],
                modes=operator["modes"],
            )
        profiles[benchmark] = Core1Profile(
            benchmark=benchmark,
            domain=row["domain"],
            primary_method=primary_method,
            operators=resolved,
            source={
                "kind": row["source_kind"],
                "id": row["source_id"],
                "revision": row["revision"],
            },
        )
    return profiles

