#!/usr/bin/env python3
"""Calibrate the clean WebShop validation set from frozen-seed outcomes only."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.contracts import TaskManifest  # noqa: E402
from rsebench.core1.dataset import rehash_task  # noqa: E402
from rsebench.evolution.skilladaptor_executor import (  # noqa: E402
    SkillAdaptorBudget,
    SkillAdaptorExecutor,
)
from rsebench.hashing import sha256_file  # noqa: E402
from rsebench.usage import write_token_usage_artifacts  # noqa: E402
from scripts.baselines.common_env import combined_method_env, methods_root  # noqa: E402


DEFAULT_SOURCE = (
    PROJECT_ROOT / "benchmark/validation/clean_qualification_v1/webshop_source.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "benchmark/validation/clean_qualification_v1/webshop_validation_selection.json"
)
DEFAULT_RUN_ROOT = (
    PROJECT_ROOT
    / "outputs/preflight/clean-qualification-v1/webshop/validation_calibration"
)
PATCH_NAMES = (
    "skilladaptor-deepseek-runtime.patch",
    "skilladaptor-evidence-hook.patch",
    "skilladaptor-webshop-static-overlay.patch",
    "skilladaptor-core1-calibration.patch",
    "skilladaptor-lexical-fault-dedup.patch",
    "skilladaptor-clean-qualification.patch",
)


def select_validation_ids(
    candidate_ids: Sequence[int],
    seed_scores: Mapping[int, float],
    *,
    execution_failures: Mapping[str, str] | None = None,
) -> list[int]:
    """Choose the first two successes and first three failures in source order."""

    if execution_failures:
        raise RuntimeError(
            "WebShop seed calibration has execution failures: "
            + json.dumps(dict(execution_failures), sort_keys=True)
        )
    missing = [goal_idx for goal_idx in candidate_ids if goal_idx not in seed_scores]
    if missing:
        raise ValueError(f"seed scores missing candidate IDs: {missing}")
    successes = [
        goal_idx for goal_idx in candidate_ids if seed_scores[goal_idx] >= 0.999
    ]
    failures = [
        goal_idx for goal_idx in candidate_ids if seed_scores[goal_idx] < 0.999
    ]
    if len(successes) < 2 or len(failures) < 3:
        raise ValueError(
            "WebShop validation calibration requires two successes and three failures"
        )
    return successes[:2] + failures[:3]


def _task(goal_idx: int, goal: dict[str, object]) -> TaskManifest:
    return rehash_task(
        TaskManifest(
            task_id=f"goal_{goal_idx}",
            benchmark="webshop",
            domain="interactive",
            prompt=str(goal["instruction_text"]),
            verifier="webshop_official_reward_v1",
            source_hash="0" * 64,
            metadata={
                "goal_idx": goal_idx,
                "target_asin": str(goal["asin"]),
                "query": str(goal["query"]),
            },
        )
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    candidate_ids = [int(value) for value in source["validation_candidates"]]
    goals = source["goals"]
    tasks_by_id = {
        goal_idx: _task(goal_idx, goals[str(goal_idx)])
        for goal_idx in candidate_ids
    }

    external_root = methods_root()
    method_root = external_root / "skilladaptor/skill-adaptor"
    webshop_root = external_root / "webshop"
    seed_skill = PROJECT_ROOT / "benchmark/core1/seeds/skilladaptor_webshop.json"
    run_dir = args.run_root.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    executor = SkillAdaptorExecutor(
        method_root=method_root,
        webshop_root=webshop_root,
        project_root=PROJECT_ROOT,
        budget=SkillAdaptorBudget(max_iterations=3, max_episode_steps=15),
        environment=combined_method_env("skilladaptor"),
    )
    executor.configure_token_run(run_dir)
    seed_scores: dict[int, float] = {}
    execution_failures: dict[str, str] = {}
    evaluation_artifacts: list[str] = []
    for cached_result in sorted(run_dir.glob("seed_evaluation*/result.json")):
        prior = json.loads(cached_result.read_text(encoding="utf-8"))
        cached_scores = {
            int(task_id.removeprefix("goal_")): float(score)
            for task_id, score in prior["per_task_scores"].items()
        }
        duplicates = set(seed_scores) & set(cached_scores)
        if any(seed_scores[value] != cached_scores[value] for value in duplicates):
            raise RuntimeError(
                "cached WebShop calibration contains conflicting seed scores"
            )
        seed_scores.update(cached_scores)
        execution_failures.update(
            prior.get("diagnostics", {}).get("execution_failures") or {}
        )
        evaluation_artifacts.append(
            cached_result.resolve().relative_to(PROJECT_ROOT).as_posix()
        )
    unexpected = sorted(set(seed_scores) - set(candidate_ids))
    if unexpected:
        raise RuntimeError(
            f"cached WebShop calibration contains unexpected candidates: {unexpected}"
        )
    pending_ids = [value for value in candidate_ids if value not in seed_scores]
    if pending_ids:
        evaluation_dir = (
            run_dir / "seed_evaluation"
            if not seed_scores
            else run_dir / f"seed_evaluation_incremental_{len(seed_scores)}"
        )
        evaluation = executor.evaluate(
            skill_path=seed_skill,
            clean_test=[tasks_by_id[value] for value in pending_ids],
            output_dir=evaluation_dir,
            stage="calibration",
        )
        expected_task_ids = {f"goal_{value}" for value in pending_ids}
        if set(evaluation.per_task_scores) != expected_task_ids:
            raise RuntimeError(
                "WebShop calibration did not evaluate the exact pending candidate set"
            )
        seed_scores.update(
            {
                int(task_id.removeprefix("goal_")): float(score)
                for task_id, score in evaluation.per_task_scores.items()
            }
        )
        execution_failures.update(
            evaluation.diagnostics.get("execution_failures") or {}
        )
        evaluation_artifacts.append(
            (evaluation_dir / "result.json")
            .resolve()
            .relative_to(PROJECT_ROOT)
            .as_posix()
        )
    attempt_payload = {
        "candidate_ids": candidate_ids,
        "candidate_seed_scores": {
            str(value): seed_scores[value] for value in candidate_ids
        },
        "execution_failures": execution_failures,
        "evaluation_artifacts": evaluation_artifacts,
    }
    (run_dir / "calibration_attempt.json").write_text(
        json.dumps(attempt_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    selected = select_validation_ids(
        candidate_ids,
        seed_scores,
        execution_failures=execution_failures,
    )
    patch_root = PROJECT_ROOT / "patches/baselines"
    patch_hashes = {
        name: sha256_file(patch_root / name) for name in PATCH_NAMES
    }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=external_root / "skilladaptor",
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    token_usage = write_token_usage_artifacts(run_dir / "token_usage")
    payload = {
        "schema_version": "rsebench.clean-webshop-validation-selection.v1",
        "candidate_partition": "official_validation_500_1500",
        "candidate_ids": candidate_ids,
        "candidate_seed_scores": {
            str(goal_idx): seed_scores[goal_idx] for goal_idx in candidate_ids
        },
        "execution_failures": execution_failures,
        "evaluation_artifacts": evaluation_artifacts,
        "policy": "first_two_seed_successes_plus_first_three_seed_failures",
        "selected_ids": selected,
        "selected_seed_score": sum(seed_scores[value] for value in selected)
        / len(selected),
        "uses_evolved_outcomes": False,
        "uses_clean_test_outcomes": False,
        "baseline": {
            "name": "skilladaptor",
            "revision": revision,
            "seed_skill_hash": sha256_file(seed_skill),
            "patch_hashes": patch_hashes,
        },
        "runtime": {
            "model": "deepseek-v4-flash",
            "max_episode_steps": 15,
            "retrieval_mode": "lexical",
            "retrieval_threshold": 0.10,
        },
        "token_usage": token_usage,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
