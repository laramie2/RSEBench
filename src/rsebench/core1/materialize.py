"""Freeze Core-1 profiles, runtime specs, and paired static manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from rsebench.contracts import StrictModel
from rsebench.evidence import EvidenceStage, RuntimeNoiseSpec, canonical_hash, write_record


class Core1Sizes(StrictModel):
    evolution: int = Field(ge=1)
    validation: int = Field(ge=0)
    clean_test: int = Field(ge=1)


class Core1NoiseProfile(StrictModel):
    version: int = 1
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    primary_method: str = Field(min_length=1)
    stage: EvidenceStage
    operator: str = Field(min_length=1)
    form: Literal["static", "runtime"]
    mode: Literal["rule", "model", "hybrid"]
    severity: Literal["L2"] = "L2"
    seed: int
    sizes: Core1Sizes
    selector: str | None = None
    selector_parameters: dict[str, Any] = Field(default_factory=dict)
    budget: int = Field(default=1, ge=1)
    protected_fields: list[str] = Field(default_factory=list)
    failure_policy: Literal["record_inapplicable"] = "record_inapplicable"
    operator_version: str = "v1"
    model: Literal["deepseek-v4-flash"] = "deepseek-v4-flash"
    thinking: Literal[False] = False
    token_cap: int = Field(ge=1)
    source_revision: str = Field(min_length=1)

    @model_validator(mode="after")
    def stage_matches_form(self) -> "Core1NoiseProfile":
        runtime = self.stage in {EvidenceStage.trajectory, EvidenceStage.feedback}
        if runtime != (self.form == "runtime"):
            raise ValueError("N1/N2 must be static and N3/N4 must be runtime")
        if runtime and not self.selector:
            raise ValueError("runtime Core-1 profile requires selector")
        return self


class StaticPairManifest(StrictModel):
    benchmark: str
    domain: str
    stage: EvidenceStage
    operator: str
    operator_version: str
    task_id: str
    seed: int
    clean_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    noisy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    clean_path: str
    noisy_path: str
    gates: dict[str, bool]
    source_revision: str

    @model_validator(mode="after")
    def require_hard_gates(self) -> "StaticPairManifest":
        required = {
            "structural_valid",
            "label_invariant",
            "solvable",
            "answer_leak_free",
        }
        if set(self.gates) != required or not all(self.gates.values()):
            raise ValueError("static pair requires every hard gate to pass")
        return self


def load_core1_noise_profile(path: str | Path) -> Core1NoiseProfile:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Core1NoiseProfile.model_validate(payload)


def materialize_core1_profile(
    profile_path: str | Path,
    *,
    output_root: str | Path = "benchmark/core1",
) -> Path:
    profile = load_core1_noise_profile(profile_path)
    root = Path(output_root)
    if profile.form == "runtime":
        destination = root / "runtime" / profile.benchmark / f"{profile.stage.value}.json"
        spec = RuntimeNoiseSpec(
            stage=profile.stage,
            operator=profile.operator,
            benchmark=profile.benchmark,
            domain=profile.domain,
            seed=profile.seed,
            selector=profile.selector or "",
            selector_parameters=profile.selector_parameters,
            budget=profile.budget,
            protected_fields=profile.protected_fields,
            failure_policy=profile.failure_policy,
            version=profile.operator_version,
        )
        write_record(destination, spec)
        return destination
    destination = (
        root
        / "static"
        / profile.benchmark
        / profile.stage.value
        / "profile.json"
    )
    write_record(destination, profile)
    return destination


def freeze_static_pair(
    *,
    profile: Core1NoiseProfile,
    task_id: str,
    clean_payload: Any,
    noisy_payload: Any,
    output_root: str | Path,
    clean_test_ids: set[str],
    gates: dict[str, bool],
) -> Path:
    if profile.form != "static":
        raise ValueError("freeze_static_pair requires an N1/N2 profile")
    if task_id in clean_test_ids:
        raise ValueError("clean test task cannot appear in static noisy records")
    root = (
        Path(output_root)
        / "static"
        / profile.benchmark
        / profile.stage.value
        / task_id
    )
    clean_path = root / "clean.json"
    noisy_path = root / "noisy.json"
    write_record(clean_path, clean_payload)
    write_record(noisy_path, noisy_payload)
    manifest = StaticPairManifest(
        benchmark=profile.benchmark,
        domain=profile.domain,
        stage=profile.stage,
        operator=profile.operator,
        operator_version=profile.operator_version,
        task_id=task_id,
        seed=profile.seed,
        clean_hash=canonical_hash(clean_payload),
        noisy_hash=canonical_hash(noisy_payload),
        clean_path=str(clean_path),
        noisy_path=str(noisy_path),
        gates=gates,
        source_revision=profile.source_revision,
    )
    manifest_path = root / "manifest.json"
    write_record(manifest_path, manifest)
    return manifest_path

