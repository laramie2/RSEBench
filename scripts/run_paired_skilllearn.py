#!/usr/bin/env python3
"""Run paired SkillLearnBench evolution through the DeepSeek API backend."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rsebench.core1.dataset import resolve_split_paths
from rsebench.evidence import RuntimeNoiseSpec
from rsebench.evolution.contracts import EvolutionSplitManifest
from rsebench.evolution.runner import PairedEvolutionRunner
from rsebench.evolution.skilllearn_executor import (
    DockerSkillLearnBackend,
    SkillLearnExecutor,
)
from rsebench.providers.deepseek import DeepSeekClient
from scripts.baselines.common_env import methods_root


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--seed-skill", type=Path, required=True)
    parser.add_argument("--evidence-spec", type=Path)
    parser.add_argument("--feedback-mode", choices=("self", "teacher"), default="self")
    parser.add_argument(
        "--provider-config",
        type=Path,
        default=Path("configs/pilot/deepseek-v4-flash-generation.yaml"),
    )
    parser.add_argument("--output-root", type=Path, default=Path("outputs/runs/core1-screen"))
    parser.add_argument("--method-seed", type=int, default=20260813)
    parser.add_argument("--train-limit", type=int, default=1)
    parser.add_argument("--test-limit", type=int, default=4)
    parser.add_argument(
        "--seed-score-min",
        type=float,
        help="exclusive lower seed-score gate for validation runs",
    )
    parser.add_argument(
        "--seed-score-max",
        type=float,
        help="exclusive upper seed-score gate for validation runs",
    )
    args = parser.parse_args()
    seed_score_interval = None
    if args.seed_score_min is not None or args.seed_score_max is not None:
        if args.seed_score_min is None or args.seed_score_max is None:
            parser.error("--seed-score-min and --seed-score-max must be used together")
        seed_score_interval = (args.seed_score_min, args.seed_score_max)

    split = EvolutionSplitManifest.model_validate_json(
        args.split.read_text(encoding="utf-8")
    )
    client = DeepSeekClient.from_yaml(args.provider_config)
    external_methods = methods_root()
    data_root = Path(
        os.environ.get("RSEBENCH_DATA_ROOT", external_methods.parents[1] / "data")
    )
    split = resolve_split_paths(
        split,
        project_root=PROJECT_ROOT,
        data_root=data_root,
        methods_root=external_methods,
    )
    split = split.model_copy(
        update={
            "train": split.train[: args.train_limit],
            "clean_test": split.clean_test[: args.test_limit],
        }
    )
    if not split.train or not split.clean_test:
        raise ValueError("SkillLearn paired run requires nonempty train and clean test")
    spec = (
        RuntimeNoiseSpec.model_validate_json(
            args.evidence_spec.read_text(encoding="utf-8")
        )
        if args.evidence_spec
        else None
    )
    backend = DockerSkillLearnBackend(client=client)
    executor = SkillLearnExecutor(
        client=client,
        backend=backend,
        evidence_spec=spec,
        feedback_mode=args.feedback_mode,
        ledger_dir=args.output_root / "pending-token-ledger",
        run_id="pending",
    )
    method = (
        "skilllearn_teacher_feedback"
        if args.feedback_mode == "teacher"
        else "skilllearn_self_feedback"
    )
    result = PairedEvolutionRunner(executor).run(
        method=method,
        split=split,
        seed_skill_path=args.seed_skill,
        method_seed=args.method_seed,
        parameters={
            "model": "deepseek-v4-flash",
            "thinking": "disabled",
            "evidence_stage": spec.stage.value if spec else None,
        },
        output_root=args.output_root,
        seed_score_interval=seed_score_interval,
    )
    print(result.run_dir)


if __name__ == "__main__":
    main()
