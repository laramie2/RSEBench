#!/usr/bin/env python3
"""Run one budget-locked clean SkillOpt baseline qualification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = PROJECT_ROOT / "src"
for source in reversed((PROJECT_SRC, PROJECT_ROOT)):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from rsebench.core1.dataset import resolve_clean_split_paths  # noqa: E402
from rsebench.evolution.clean_bridge import build_clean_runtime_split  # noqa: E402
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
)
from rsebench.evolution.clean_runner import CleanEvolutionRunner  # noqa: E402
from rsebench.evolution.pairs import build_clean_arm_manifest  # noqa: E402
from rsebench.evolution.skillopt_executor import (  # noqa: E402
    SkillOptBudget,
    SkillOptExecutor,
)
from rsebench.hashing import sha256_file  # noqa: E402
from rsebench.experiments.runtime import load_runtime_identity  # noqa: E402
from rsebench.experiments.preflight import (  # noqa: E402
    SUPPORTED_QUALIFICATION_VERSIONS,
    TaskCounts,
    expected_skillopt_task_counts,
)
from rsebench.selection.clean_view import load_clean_runtime_view  # noqa: E402
from scripts.baselines.common_env import combined_method_env, methods_root  # noqa: E402


METHOD_SEEDS = (20260813, 20260814, 20260815)
_SEEDS = {
    "spreadsheetbench_verified": "skillopt/envs/spreadsheetbench/skills/initial.md",
    "officeqa_full": "skillopt/envs/officeqa/skills/initial.md",
}
EXPECTED = {
    "spreadsheetbench_verified": SkillOptBudget(
        max_steps=3,
        batch_size=7,
        workers=2,
        max_turns=3,
        max_completion_tokens=2048,
    ),
    "officeqa_full": SkillOptBudget(
        max_steps=3,
        batch_size=4,
        workers=2,
        max_turns=12,
        max_completion_tokens=4096,
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--method-seed", type=int, choices=METHOD_SEEDS, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _runtime_payload(budget: SkillOptBudget) -> dict[str, int]:
    return {
        "max_steps": budget.max_steps,
        "batch_size": budget.batch_size,
        "workers": budget.workers,
        "max_tool_turns": budget.max_turns,
        "max_completion_tokens": budget.max_completion_tokens,
    }


def _policy(benchmark: str) -> CleanQualificationPolicy:
    if benchmark == "officeqa_full":
        return CleanQualificationPolicy(
            min_parseable_answer_rate=0.80,
            max_systemic_failure_rate=0.05,
        )
    return CleanQualificationPolicy()


_LOCATOR_KEYS = {
    "artifact_path",
    "gold_workbook_path",
    "official_instance_path",
    "retrieval_fixture",
    "static_noise_path",
}


def _metadata_paths(value, *, key: str | None = None):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _metadata_paths(child, key=child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _metadata_paths(child, key=key)
    elif isinstance(value, str) and (
        key in _LOCATOR_KEYS or (key is not None and key.endswith("_path"))
    ):
        yield value


def _validate_resolved_artifacts(
    split: CleanEvolutionSplitManifest,
) -> list[str]:
    paths: set[str] = set()
    for task in split.train + split.validation + split.clean_test:
        if task.artifact_path:
            paths.add(task.artifact_path)
        paths.update(_metadata_paths(task.metadata))
    for value in sorted(paths):
        if value.startswith("rsebench-"):
            raise ValueError(f"unresolved portable artifact path: {value}")
        if not Path(value).exists():
            raise FileNotFoundError(f"clean qualification artifact is missing: {value}")
    return sorted(paths)


def _write_json(path: Path, payload: dict, *, immutable: bool) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if immutable and path.exists() and path.read_text(encoding="utf-8") != encoded:
        raise FileExistsError(f"different clean dry run already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _write_preflight_audit(
    output_root: Path,
    *,
    split: CleanEvolutionSplitManifest,
    method_seed: int,
    artifact_count: int,
) -> None:
    path = output_root / "manifest_audit.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {
            "schema_version": "rsebench.clean-skillopt-preflight.v1",
            "benchmarks": {},
        }
    payload["benchmarks"][split.benchmark] = {
        "method_seed": method_seed,
        "source_hash": split.source_hash,
        "task_counts": {
            "train": len(split.train),
            "validation": len(split.validation),
            "clean_test": len(split.clean_test),
        },
        "runtime": split.metadata["runtime"],
        "resolved_artifact_count": artifact_count,
        "arm": "clean",
        "provider_calls": 0,
    }
    payload["all_ready"] = set(payload["benchmarks"]) == set(EXPECTED)
    _write_json(path, payload, immutable=False)


def run_manifest(
    manifest: Path,
    *,
    method_seed: int,
    output_root: Path,
    dry_run: bool = False,
) -> Path:
    """Execute one formal clean SkillOpt manifest and return its run directory."""

    if method_seed not in METHOD_SEEDS:
        raise ValueError(f"unsupported formal method seed: {method_seed}")
    split = load_clean_runtime_view(manifest)
    try:
        budget = EXPECTED[split.benchmark]
    except KeyError as exc:
        raise ValueError(
            f"unsupported clean SkillOpt benchmark: {split.benchmark}"
        ) from exc
    expected_runtime = _runtime_payload(budget)
    if split.metadata.get("runtime") != expected_runtime:
        raise ValueError(
            f"{split.benchmark} runtime metadata differs from formal settings"
        )
    qualification_version = str(
        split.metadata.get("qualification_version") or "clean-qualification-v1"
    )
    if qualification_version not in SUPPORTED_QUALIFICATION_VERSIONS:
        raise ValueError(
            f"unsupported SkillOpt qualification version: {qualification_version}"
        )
    actual_counts = TaskCounts(
        train=len(split.train),
        validation=len(split.validation),
        clean_test=len(split.clean_test),
    )
    expected_counts = expected_skillopt_task_counts(
        split.benchmark,
        qualification_version,
    )
    if expected_counts is None or actual_counts != expected_counts:
        raise ValueError(
            f"{split.benchmark} task counts differ from formal settings: "
            f"{actual_counts.model_dump()} != "
            f"{expected_counts.model_dump() if expected_counts is not None else None}"
        )
    identity, attempt = load_runtime_identity(
        required=(
            qualification_version in {"clean-qualification-v2", "noise-screen-v1"}
            and not dry_run
        ),
        benchmark=split.benchmark,
        method_seed=method_seed,
    )

    environment = combined_method_env("skillopt")
    external_methods = methods_root()
    method_root = external_methods / "skillopt"
    data_root = Path(environment["RSEBENCH_DATA_ROOT"])
    split = resolve_clean_split_paths(
        split,
        project_root=PROJECT_ROOT,
        data_root=data_root,
        methods_root=external_methods,
    )
    seed_skill = method_root / _SEEDS[split.benchmark]
    if not seed_skill.is_file():
        raise FileNotFoundError(f"SkillOpt seed skill is missing: {seed_skill}")
    executor = SkillOptExecutor(
        method_root=method_root,
        data_root=data_root,
        environment=environment,
        budget=budget,
    )
    parameters = {
        "qualification_version": qualification_version,
        "model": "deepseek-v4-flash",
        "thinking": "disabled",
        "temperature": 0,
        "train_tasks": len(split.train),
        "validation_tasks": len(split.validation),
        "clean_test_tasks": len(split.clean_test),
        "runtime": expected_runtime,
    }
    if dry_run:
        resolved_artifacts = _validate_resolved_artifacts(split)
        runtime_split = build_clean_runtime_split(split)
        seed_hash = sha256_file(seed_skill)
        arm = build_clean_arm_manifest(
            runtime_split,
            method="skillopt",
            method_seed=method_seed,
            seed_skill_hash=seed_hash,
            parameters=parameters,
        )
        run_dir = Path(output_root) / split.benchmark / str(method_seed) / "dry-run"
        prepared = executor.prepare_evolution(
            arm=arm,
            split=runtime_split,
            seed_skill_path=seed_skill,
            output_dir=run_dir / "clean",
        )
        payload = {
            "schema_version": "rsebench.clean-skillopt-dry-run.v1",
            "benchmark": split.benchmark,
            "method_seed": method_seed,
            "split_source_hash": split.source_hash,
            "seed_skill_hash": seed_hash,
            "task_counts": {
                "train": len(split.train),
                "validation": len(split.validation),
                "clean_test": len(split.clean_test),
            },
            "resolved_artifacts": resolved_artifacts,
            "arm_manifest": arm.model_dump(mode="json"),
            "native_split": str(prepared.native_split),
            "native_output": str(prepared.native_output),
            "native_command": prepared.command,
            "parameters": parameters,
            "provider_calls": 0,
            "identity": identity.model_dump(mode="json") if identity else None,
        }
        _write_json(run_dir / "dry_run.json", payload, immutable=True)
        _write_preflight_audit(
            Path(output_root),
            split=split,
            method_seed=method_seed,
            artifact_count=len(resolved_artifacts),
        )
        return run_dir
    result = CleanEvolutionRunner(executor).run(
        method="skillopt",
        split=split,
        seed_skill_path=seed_skill,
        method_seed=method_seed,
        parameters=parameters,
        output_root=Path(output_root) / split.benchmark / str(method_seed),
        policy=_policy(split.benchmark),
        identity=identity,
        attempt=attempt,
    )
    return Path(result.run_dir)


def main() -> None:
    args = build_parser().parse_args()
    run_dir = run_manifest(
        args.manifest,
        method_seed=args.method_seed,
        output_root=args.output_root,
        dry_run=args.dry_run,
    )
    print(run_dir)
    if not args.dry_run:
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        print(json.dumps(result["qualification"], sort_keys=True))


if __name__ == "__main__":
    main()
