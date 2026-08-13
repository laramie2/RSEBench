#!/usr/bin/env python3
"""Run paired SkillLearnBench evolution through the DeepSeek API backend."""

from __future__ import annotations

import argparse
from pathlib import Path

from rsebench.evidence import RuntimeNoiseSpec
from rsebench.evolution.contracts import EvolutionSplitManifest
from rsebench.evolution.runner import PairedEvolutionRunner
from rsebench.evolution.skilllearn_executor import (
    DockerSkillLearnBackend,
    SkillLearnExecutor,
)
from rsebench.providers.deepseek import DeepSeekClient


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
    args = parser.parse_args()

    split = EvolutionSplitManifest.model_validate_json(
        args.split.read_text(encoding="utf-8")
    )
    spec = (
        RuntimeNoiseSpec.model_validate_json(
            args.evidence_spec.read_text(encoding="utf-8")
        )
        if args.evidence_spec
        else None
    )
    client = DeepSeekClient.from_yaml(args.provider_config)
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
    )
    print(result.run_dir)


if __name__ == "__main__":
    main()
