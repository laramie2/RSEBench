#!/usr/bin/env python
"""Evaluate a frozen SkillAdaptor bank on an untouched WebShop test split."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scripts.baselines.common_env import MODEL, combined_method_env  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method-root", type=Path, required=True)
    parser.add_argument("--webshop-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--skills", type=Path, required=True)
    parser.add_argument("--max-episode-steps", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    method_root = args.method_root.resolve()
    webshop_root = args.webshop_root.resolve()
    sys.path.insert(0, str(method_root))
    sys.path.insert(0, str(webshop_root))

    from adapters.webshop_adapter import (
        SkillAugmentedLLMPolicy,
        WebShopEnvWrapper,
    )
    from core.skill_bank import SkillBankManager

    environment = combined_method_env("skilladaptor")
    config = {
        "api_key": environment["SkillAdaptor_API_KEY"],
        "base_url": environment["SkillAdaptor_BASE_URL"],
        "model": MODEL,
    }
    manager = SkillBankManager()
    manager.load(args.skills)
    skill_bank = {skill.id: skill for skill in manager.list_skills()}
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    goal_indices = [int(value) for value in manifest.get("test_tasks") or []]
    if not goal_indices:
        raise ValueError("WebShop evaluation manifest has no test_tasks")
    env = WebShopEnvWrapper(num_products=1000, webshop_path=webshop_root)
    scores: dict[str, float] = {}
    episode_diagnostics: dict[str, dict[str, object]] = {}
    try:
        for goal_idx in goal_indices:
            policy = SkillAugmentedLLMPolicy(
                config,
                skill_bank=skill_bank,
                top_k_skills=3,
                embedding_api_key="",
                embedding_base_url="",
            )
            episode = env.run_episode(
                goal_idx=goal_idx,
                policy=policy,
                max_steps=args.max_episode_steps,
                verbose=False,
            )
            task_id = f"goal_{goal_idx}"
            score = float(episode.get("total_reward", 0.0))
            scores[task_id] = score
            episode_diagnostics[task_id] = {
                "success": bool(episode.get("success", False)),
                "num_steps": int(episode.get("num_steps", 0)),
            }
    finally:
        env.close()
    result = {
        "score": sum(scores.values()) / len(scores),
        "per_task_scores": scores,
        "diagnostics": {
            "sample_size": len(scores),
            "episodes": episode_diagnostics,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
