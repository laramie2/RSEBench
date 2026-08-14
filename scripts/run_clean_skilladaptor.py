#!/usr/bin/env python3
"""Run one budget-locked clean SkillAdaptor WebShop qualification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.evolution.clean_bridge import build_clean_runtime_split  # noqa: E402
from rsebench.evolution.clean_contracts import (  # noqa: E402
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
)
from rsebench.evolution.clean_runner import CleanEvolutionRunner  # noqa: E402
from rsebench.evolution.pairs import build_clean_arm_manifest  # noqa: E402
from rsebench.evolution.skilladaptor_executor import (  # noqa: E402
    SkillAdaptorBudget,
    SkillAdaptorExecutor,
)
from rsebench.hashing import sha256_file  # noqa: E402
from scripts.baselines.common_env import combined_method_env, methods_root  # noqa: E402


METHOD_SEEDS = (20260813, 20260814, 20260815)
BUDGET = SkillAdaptorBudget(max_iterations=3, max_episode_steps=15)
RUNTIME = {
    "max_iterations": 3,
    "max_episode_steps": 15,
    "min_sample_size": 5,
}
PATCH_NAMES = (
    "skilladaptor-deepseek-runtime.patch",
    "skilladaptor-evidence-hook.patch",
    "skilladaptor-webshop-static-overlay.patch",
    "skilladaptor-core1-calibration.patch",
    "skilladaptor-lexical-fault-dedup.patch",
    "skilladaptor-clean-qualification.patch",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seed-skill", type=Path, required=True)
    parser.add_argument("--method-seed", type=int, choices=METHOD_SEEDS, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _patch_hashes() -> dict[str, str]:
    root = PROJECT_ROOT / "patches/baselines"
    return {name: sha256_file(root / name) for name in PATCH_NAMES}


def _write_json(path: Path, payload: dict[str, Any], *, immutable: bool) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if immutable and path.exists() and path.read_text(encoding="utf-8") != encoded:
        raise FileExistsError(f"different SkillAdaptor preflight already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _calibration_selection_path(
    manifest: Path,
    split: CleanEvolutionSplitManifest,
) -> Path:
    local = manifest.parent / "webshop_validation_selection.json"
    locator = str(split.metadata.get("calibration_selection_path") or "").strip()
    if not locator:
        return local
    prefix = "rsebench-project://"
    if locator.startswith(prefix):
        return PROJECT_ROOT / locator.removeprefix(prefix)
    path = Path(locator)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _calibration_evidence(
    manifest: Path,
    split: CleanEvolutionSplitManifest,
) -> dict[str, Any]:
    selection_path = _calibration_selection_path(manifest, split)
    if not selection_path.is_file():
        if split.metadata.get("calibration_selection_path"):
            raise FileNotFoundError(
                f"declared WebShop calibration selection is missing: {selection_path}"
            )
        return {"available": False}
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selected_ids = [f"goal_{value}" for value in selection["selected_ids"]]
    expected_ids = [task.task_id for task in split.validation]
    if selected_ids != expected_ids:
        raise ValueError("WebShop selection IDs differ from frozen validation tasks")
    if selection.get("execution_failures"):
        raise RuntimeError("WebShop validation calibration has execution failures")

    events: list[dict[str, Any]] = []
    for artifact in selection.get("evaluation_artifacts") or []:
        result_path = PROJECT_ROOT / str(artifact)
        audit_path = result_path.parent / "retrieval_audit/calibration_test.jsonl"
        if not audit_path.is_file():
            raise FileNotFoundError(
                f"WebShop calibration retrieval audit is missing: {audit_path}"
            )
        events.extend(
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    per_episode: dict[str, set[str]] = {}
    retrieved: dict[str, list[str]] = {}
    injected: dict[str, list[str]] = {}
    for event in events:
        episode_id = str(event.get("episode_id") or "")
        event_name = str(event.get("event") or "")
        per_episode.setdefault(episode_id, set()).add(event_name)
        if event_name == "retrieval":
            retrieved[episode_id] = list(event.get("retrieved_skill_ids") or [])
        if event_name == "prompt_injection":
            injected[episode_id] = list(event.get("injected_skill_ids") or [])
    for task_id in expected_ids:
        if per_episode.get(task_id) != {"retrieval", "prompt_injection"}:
            raise RuntimeError(f"incomplete retrieval audit for {task_id}")
        if not retrieved.get(task_id) or not injected.get(task_id):
            raise RuntimeError(f"seed skill did not reach WebShop prompt for {task_id}")
    return {
        "available": True,
        "candidate_count": len(selection["candidate_ids"]),
        "selected_ids": selected_ids,
        "selected_seed_score": selection["selected_seed_score"],
        "execution_failures": {},
        "selected_retrieval_audited": True,
        "general_seed_reached_each_prompt": True,
        "uses_evolved_outcomes": selection["uses_evolved_outcomes"],
        "uses_clean_test_outcomes": selection["uses_clean_test_outcomes"],
    }


def run_manifest(
    manifest: Path,
    *,
    seed_skill: Path,
    method_seed: int,
    output_root: Path,
    dry_run: bool = False,
) -> Path:
    """Execute one formal clean SkillAdaptor manifest."""

    if method_seed not in METHOD_SEEDS:
        raise ValueError(f"unsupported formal method seed: {method_seed}")
    split = CleanEvolutionSplitManifest.model_validate_json(
        manifest.read_text(encoding="utf-8")
    )
    if split.benchmark != "webshop" or split.domain != "interactive":
        raise ValueError("clean SkillAdaptor launcher only supports WebShop")
    sizes = (len(split.train), len(split.validation), len(split.clean_test))
    if sizes != (5, 5, 20):
        raise ValueError("clean SkillAdaptor qualification requires exact 5/5/20")
    if split.metadata.get("runtime") != RUNTIME:
        raise ValueError("WebShop runtime metadata differs from formal settings")
    qualification_version = str(
        split.metadata.get("qualification_version") or "clean-qualification-v1"
    )
    if qualification_version not in {
        "clean-qualification-v1",
        "clean-qualification-v2",
    }:
        raise ValueError(
            f"unsupported WebShop qualification version: {qualification_version}"
        )
    seed_skill = seed_skill.resolve()
    if not seed_skill.is_file():
        raise FileNotFoundError(f"SkillAdaptor seed skill is missing: {seed_skill}")

    patch_hashes = _patch_hashes()
    parameters = {
        "qualification_version": qualification_version,
        "model": "deepseek-v4-flash",
        "temperature": 0,
        "thinking": "disabled",
        "train_tasks": 5,
        "validation_tasks": 5,
        "clean_test_tasks": 20,
        "runtime": RUNTIME,
        "retrieval_mode": "lexical",
        "retrieval_threshold": 0.10,
        "patch_hashes": patch_hashes,
    }
    if dry_run:
        runtime_split = build_clean_runtime_split(split)
        seed_hash = sha256_file(seed_skill)
        arm = build_clean_arm_manifest(
            runtime_split,
            method="skilladaptor",
            method_seed=method_seed,
            seed_skill_hash=seed_hash,
            parameters=parameters,
        )
        run_dir = output_root.resolve()
        payload = {
            "schema_version": "rsebench.clean-skilladaptor-preflight.v1",
            "benchmark": split.benchmark,
            "method_seed": method_seed,
            "split_source_hash": split.source_hash,
            "seed_skill_hash": seed_hash,
            "task_counts": {
                "train": 5,
                "validation": 5,
                "clean_test": 20,
            },
            "runtime": RUNTIME,
            "parameters": parameters,
            "arm_manifest": arm.model_dump(mode="json"),
            "calibration_evidence": _calibration_evidence(manifest, split),
            "provider_calls": 0,
            "token_events": 0,
            "all_ready": True,
        }
        _write_json(run_dir / "preflight.json", payload, immutable=True)
        return run_dir

    external_methods = methods_root()
    executor = SkillAdaptorExecutor(
        method_root=external_methods / "skilladaptor/skill-adaptor",
        webshop_root=external_methods / "webshop",
        project_root=PROJECT_ROOT,
        environment=combined_method_env("skilladaptor"),
        budget=BUDGET,
    )
    result = CleanEvolutionRunner(executor).run(
        method="skilladaptor",
        split=split,
        seed_skill_path=seed_skill,
        method_seed=method_seed,
        parameters=parameters,
        output_root=output_root.resolve() / str(method_seed),
        policy=CleanQualificationPolicy(),
    )
    return Path(result.run_dir)


def main() -> None:
    args = build_parser().parse_args()
    run_dir = run_manifest(
        args.manifest,
        seed_skill=args.seed_skill,
        method_seed=args.method_seed,
        output_root=args.output_root,
        dry_run=args.dry_run,
    )
    print(run_dir)


if __name__ == "__main__":
    main()
