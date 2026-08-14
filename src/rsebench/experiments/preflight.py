"""Provider-free validation and identity expansion for formal experiment matrices."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Literal

import yaml
from pydantic import Field, field_validator, model_validator

import rsebench
from rsebench.contracts import StrictModel
from rsebench.evidence import canonical_hash
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.experiments.bootstrap import (
    BaselineFingerprint,
    load_patch_series,
    verify_baseline,
)
from rsebench.experiments.contracts import (
    ExperimentIdentity,
    ExperimentIdentityInput,
    build_experiment_identity,
)
from rsebench.experiments.scheduler import ScheduledUnit
from rsebench.hashing import sha256_file
from rsebench.registry import load_registry


FORMAL_METHOD_SEEDS = (20260813, 20260814, 20260815)
_CHECKOUT_NAMES = {
    "skilllearn_self_feedback": "skilllearnbench",
    "skilllearn_teacher_feedback": "skilllearnbench",
}


class TaskCounts(StrictModel):
    train: int = Field(ge=1)
    validation: int = Field(ge=1)
    clean_test: int = Field(ge=1)


class ExperimentCell(StrictModel):
    key: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    launcher: str = Field(min_length=1)
    manifest: str = Field(min_length=1)
    seed_skill: str = Field(min_length=1)
    seed_skill_argument: bool = True
    image_manifest: str | None = None
    task_counts: TaskCounts
    runtime: dict[str, Any]
    adapter_key: str = Field(min_length=1)
    adapter_max_parallel: int = Field(default=1, ge=1)
    mutable_resource_keys: list[str] = Field(default_factory=list)
    family: str | None = None

    @field_validator("mutable_resource_keys")
    @classmethod
    def validate_resource_keys(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("mutable resource keys must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("mutable resource keys must be unique")
        return value


class ExperimentMatrix(StrictModel):
    schema_version: Literal["rsebench.experiment-matrix.v1"]
    qualification_version: Literal["clean-qualification-v2"]
    stage: Literal["clean"]
    method_seeds: list[int]
    provider: Literal["deepseek"]
    model: Literal["deepseek-v4-flash"]
    temperature: float
    thinking: Literal["disabled"]
    provider_config: str = Field(min_length=1)
    output_root: str = Field(min_length=1)
    cells: list[ExperimentCell] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_formal_scope(self) -> "ExperimentMatrix":
        if tuple(self.method_seeds) != FORMAL_METHOD_SEEDS:
            raise ValueError(
                "formal clean-v2 method seeds must be 20260813/20260814/20260815"
            )
        if self.temperature != 0:
            raise ValueError("formal clean-v2 temperature must be zero")
        keys = [cell.key for cell in self.cells]
        if len(keys) != len(set(keys)):
            raise ValueError("experiment cell keys must be unique")
        return self


class ProviderConfiguration(StrictModel):
    path: str
    provider: str
    model: str
    credential_name: str
    credential_declared: bool
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PreflightUnit(StrictModel):
    key: str
    cell_key: str
    method_seed: int
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_order_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_skill_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: ExperimentIdentity
    scheduled: ScheduledUnit


class PreflightReport(StrictModel):
    schema_version: Literal["rsebench.experiment-preflight.v1"] = (
        "rsebench.experiment-preflight.v1"
    )
    matrix_path: str
    matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    package_source: str
    output_root: str
    provider_configuration: ProviderConfiguration
    baseline_fingerprints: dict[str, BaselineFingerprint]
    units: list[PreflightUnit]
    provider_calls: Literal[0] = 0
    all_ready: bool


FingerprintResolver = Callable[[str], BaselineFingerprint]


def load_experiment_matrix(path: Path | str) -> ExperimentMatrix:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ExperimentMatrix.model_validate(payload)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _repository_commit(root: Path, *, require_clean: bool) -> str:
    if require_clean:
        dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
        if dirty:
            raise RuntimeError("formal preflight requires a clean git worktree")
    commit = _git(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("repository HEAD is not a full Git commit")
    return commit


def _validate_package_source(root: Path, package_file: Path | str | None) -> Path:
    source = Path(package_file or rsebench.__file__).resolve()
    expected = (root / "src").resolve()
    try:
        source.relative_to(expected)
    except ValueError as exc:
        raise RuntimeError(
            f"rsebench package source is outside canonical checkout: {source}"
        ) from exc
    return source


def _methods_root(root: Path) -> Path:
    configured = os.environ.get("RSEBENCH_METHODS_ROOT")
    return Path(configured).resolve() if configured else root / "methods/external"


def _resolve_path(root: Path, methods_root: Path, locator: str) -> Path:
    if locator.startswith("methods://"):
        relative = locator.removeprefix("methods://")
        return (methods_root / relative).resolve()
    if locator.startswith("rsebench-project://"):
        locator = locator.removeprefix("rsebench-project://")
    candidate = Path(locator)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _default_fingerprint_resolver(root: Path) -> FingerprintResolver:
    registry = load_registry(root / "benchmark/registry/methods.yaml")["methods"]
    methods_root = _methods_root(root)

    def resolve(name: str) -> BaselineFingerprint:
        if name not in registry:
            raise ValueError(f"unknown registered baseline: {name}")
        specification = registry[name]
        series_locator = specification.get("patch_series")
        if not series_locator:
            raise ValueError(f"baseline has no registered patch series: {name}")
        series_path = (root / str(series_locator)).resolve()
        series = load_patch_series(series_path)
        checkout = methods_root / _CHECKOUT_NAMES.get(name, name)
        return verify_baseline(
            checkout,
            series,
            series_path=series_path,
            repository=str(specification["repository"]),
            revision=str(specification["commit"]),
        )

    return resolve


def _provider_configuration(root: Path, matrix: ExperimentMatrix) -> ProviderConfiguration:
    path = _resolve_path(root, _methods_root(root), matrix.provider_config)
    if not path.is_file():
        raise FileNotFoundError(f"provider config is missing: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provider config must be a mapping")
    expected = {
        "provider": matrix.provider,
        "model": matrix.model,
        "temperature": matrix.temperature,
        "thinking": matrix.thinking,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"provider config {key} differs from experiment matrix")
    credential_name = str(payload.get("api_key_env") or "").strip()
    if not credential_name:
        raise ValueError("provider config has no credential environment name")
    dotenv_path = root / ".env"
    declared_in_dotenv = False
    if dotenv_path.is_file():
        pattern = re.compile(rf"^\s*{re.escape(credential_name)}\s*=", re.MULTILINE)
        declared_in_dotenv = bool(pattern.search(dotenv_path.read_text(encoding="utf-8")))
    declared = credential_name in os.environ or declared_in_dotenv
    if not declared:
        raise RuntimeError(
            f"provider credential name is not declared: {credential_name}"
        )
    return ProviderConfiguration(
        path=str(path),
        provider=matrix.provider,
        model=matrix.model,
        credential_name=credential_name,
        credential_declared=True,
        config_hash=sha256_file(path),
    )


def _split_hashes(split: CleanEvolutionSplitManifest) -> dict[str, str]:
    hashes: dict[str, str] = {"split": split.source_hash}
    for name in ("train", "validation", "clean_test"):
        tasks = getattr(split, name)
        hashes[name] = canonical_hash(
            [
                {"task_id": task.task_id, "source_hash": task.source_hash}
                for task in tasks
            ]
        )
    return hashes


def _task_order_hash(split: CleanEvolutionSplitManifest) -> str:
    return canonical_hash(
        {
            name: [task.task_id for task in getattr(split, name)]
            for name in ("train", "validation", "clean_test")
        }
    )


def _expanded_resources(cell: ExperimentCell, method_seed: int) -> list[str]:
    values = [
        value.format(
            method_seed=method_seed,
            cell_key=cell.key,
            benchmark=cell.benchmark,
            family=cell.family or "",
        )
        for value in cell.mutable_resource_keys
    ]
    if len(values) != len(set(values)):
        raise ValueError(f"expanded mutable resources collide within {cell.key}")
    if cell.baseline.startswith("skilllearn") and not values:
        raise ValueError("SkillLearn units require an isolated Docker resource key")
    return values


def preflight_matrix(
    matrix_path: Path | str,
    *,
    project_root: Path | str | None = None,
    package_file: Path | str | None = None,
    fingerprint_resolver: FingerprintResolver | None = None,
    require_clean_worktree: bool = True,
) -> PreflightReport:
    """Validate a formal matrix and expand identities without calling a provider."""

    root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
    path = Path(matrix_path).resolve()
    matrix = load_experiment_matrix(path)
    repository_commit = _repository_commit(root, require_clean=require_clean_worktree)
    package_source = _validate_package_source(root, package_file)
    provider = _provider_configuration(root, matrix)
    methods_root = _methods_root(root)
    resolve_fingerprint = fingerprint_resolver or _default_fingerprint_resolver(root)
    fingerprints = {
        baseline: resolve_fingerprint(baseline)
        for baseline in dict.fromkeys(cell.baseline for cell in matrix.cells)
    }
    environment_hash = canonical_hash(
        {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "provider_config_hash": provider.config_hash,
            "package_source_hash": sha256_file(package_source),
        }
    )
    output_root = _resolve_path(root, methods_root, matrix.output_root)
    try:
        output_root.relative_to((root / "outputs").resolve())
    except ValueError as exc:
        raise ValueError("output_root must be inside the project outputs directory") from exc
    units: list[PreflightUnit] = []
    output_directories: set[str] = set()
    for cell in matrix.cells:
        launcher = _resolve_path(root, methods_root, cell.launcher)
        manifest = _resolve_path(root, methods_root, cell.manifest)
        seed_skill = _resolve_path(root, methods_root, cell.seed_skill)
        if not launcher.is_file():
            raise FileNotFoundError(f"experiment launcher is missing: {launcher}")
        if not manifest.is_file():
            raise FileNotFoundError(f"clean manifest is missing: {manifest}")
        if not seed_skill.is_file():
            raise FileNotFoundError(f"seed skill is missing: {seed_skill}")
        image_manifest = None
        if cell.image_manifest is not None:
            image_manifest = _resolve_path(root, methods_root, cell.image_manifest)
            if not image_manifest.is_file():
                raise FileNotFoundError(
                    f"SkillLearn image manifest is missing: {image_manifest}"
                )
        split = CleanEvolutionSplitManifest.model_validate_json(
            manifest.read_text(encoding="utf-8")
        )
        if split.benchmark != cell.benchmark:
            raise ValueError(f"cell benchmark differs from manifest: {cell.key}")
        if split.metadata.get("qualification_version") != matrix.qualification_version:
            raise ValueError(f"manifest is not clean-qualification-v2: {cell.key}")
        actual_counts = TaskCounts(
            train=len(split.train),
            validation=len(split.validation),
            clean_test=len(split.clean_test),
        )
        if actual_counts != cell.task_counts:
            raise ValueError(f"task counts differ from matrix: {cell.key}")
        if split.metadata.get("runtime") != cell.runtime:
            raise ValueError(f"runtime differs from manifest: {cell.key}")
        manifest_hash = sha256_file(manifest)
        seed_skill_hash = sha256_file(seed_skill)
        task_order_hash = _task_order_hash(split)
        runtime = {
            **cell.runtime,
            "temperature": matrix.temperature,
            "thinking": matrix.thinking,
            "provider_config_hash": provider.config_hash,
        }
        if cell.family is not None:
            runtime["family"] = cell.family
        if image_manifest is not None:
            runtime["image_manifest_hash"] = sha256_file(image_manifest)
        for method_seed in matrix.method_seeds:
            identity = build_experiment_identity(
                ExperimentIdentityInput(
                    repository_commit=repository_commit,
                    baseline=fingerprints[cell.baseline],
                    environment_hash=environment_hash,
                    manifest_hash=manifest_hash,
                    dataset_hashes=_split_hashes(split),
                    seed_skill_hash=seed_skill_hash,
                    model=matrix.model,
                    provider=matrix.provider,
                    runtime=runtime,
                    benchmark=cell.benchmark,
                    stage=matrix.stage,
                    method_seed=method_seed,
                )
            )
            key = f"{cell.key}:{method_seed}"
            unit_output = output_root / "units" / cell.key / str(method_seed)
            output_value = str(unit_output)
            if output_value in output_directories:
                raise ValueError(f"duplicate unit output directory: {unit_output}")
            output_directories.add(output_value)
            command = [
                sys.executable,
                str(launcher),
                "--manifest",
                str(manifest),
                "--method-seed",
                str(method_seed),
                "--output-root",
                output_value,
            ]
            if cell.seed_skill_argument:
                command.extend(["--seed-skill", str(seed_skill)])
            if image_manifest is not None:
                command.extend(["--image-manifest", str(image_manifest)])
            scheduled = ScheduledUnit(
                key=key,
                experiment_id=identity.experiment_id,
                command=command,
                output_dir=output_value,
                mutable_resource_keys=_expanded_resources(cell, method_seed),
                adapter_key=cell.adapter_key,
                adapter_max_parallel=cell.adapter_max_parallel,
            )
            units.append(
                PreflightUnit(
                    key=key,
                    cell_key=cell.key,
                    method_seed=method_seed,
                    manifest_hash=manifest_hash,
                    task_order_hash=task_order_hash,
                    seed_skill_hash=seed_skill_hash,
                    identity=identity,
                    scheduled=scheduled,
                )
            )
    return PreflightReport(
        matrix_path=str(path),
        matrix_hash=sha256_file(path),
        repository_commit=repository_commit,
        package_source=str(package_source),
        output_root=str(output_root),
        provider_configuration=provider,
        baseline_fingerprints=fingerprints,
        units=units,
        provider_calls=0,
        all_ready=True,
    )


__all__ = [
    "ExperimentCell",
    "ExperimentMatrix",
    "PreflightReport",
    "PreflightUnit",
    "ProviderConfiguration",
    "TaskCounts",
    "load_experiment_matrix",
    "preflight_matrix",
]
