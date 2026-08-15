#!/usr/bin/env python3
"""Repeatedly evaluate immutable Markdown skills on one SkillLearn family."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = PROJECT_ROOT / "src"
for source in reversed((PROJECT_SRC, PROJECT_ROOT)):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
SHARED_ROOT = (
    PROJECT_ROOT.parents[1] if ".worktrees" in PROJECT_ROOT.parts else PROJECT_ROOT
)
PROVIDER_CONFIG = PROJECT_ROOT / "configs/pilot/deepseek-v4-flash-4096.yaml"
DEFAULT_IMAGE_MANIFEST = (
    PROJECT_ROOT / "outputs/preflight/noise-screen-v1/skilllearn_image_manifest.json"
)

from rsebench.core1.dataset import resolve_candidate_paths  # noqa: E402
from rsebench.evidence import canonical_hash  # noqa: E402
from rsebench.evolution.artifact_evaluation import (  # noqa: E402
    evaluate_repeated_artifacts,
)
from rsebench.evolution.skilllearn_executor import (  # noqa: E402
    DockerSkillLearnBackend,
    SkillLearnExecutor,
)
from rsebench.hashing import sha256_file  # noqa: E402
from rsebench.providers.deepseek import DeepSeekClient  # noqa: E402
from rsebench.selection.contracts import StableSplitCandidate  # noqa: E402
from rsebench.selection.qualification import (  # noqa: E402
    select_candidate_evaluation_tasks,
)
from scripts.baselines.common_env import methods_root  # noqa: E402


ORDER_POLICY = "cyclic_rotation"
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.0
THINKING = "disabled"


def parse_artifact_arguments(
    values: list[str], *, project_root: Path = PROJECT_ROOT
) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        label = label.strip()
        raw_path = raw_path.strip()
        if not separator or not label or not raw_path:
            raise ValueError(f"artifact must use LABEL=PATH: {value}")
        if label in artifacts:
            raise ValueError(f"duplicate artifact label: {label}")
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"artifact {label} not found: {path}")
        artifacts[label] = path
    if not artifacts:
        raise ValueError("at least one --artifact is required")
    return artifacts


def resolve_selection_candidate_paths(
    candidate: StableSplitCandidate,
) -> StableSplitCandidate:
    return resolve_candidate_paths(
        candidate,
        project_root=PROJECT_ROOT,
        data_root=SHARED_ROOT / "data",
        methods_root=methods_root(),
    )


def build_skilllearn_executor(*, output_dir: Path) -> SkillLearnExecutor:
    client = DeepSeekClient.from_yaml(PROVIDER_CONFIG)
    backend = DockerSkillLearnBackend(
        client=client,
        max_turns=16,
        require_prebuilt=True,
    )
    return SkillLearnExecutor(
        client=client,
        backend=backend,
        evidence_spec=None,
        feedback_mode="self",
        ledger_dir=output_dir / "pending-token-ledger",
        run_id="pending",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument(
        "--evaluation-role",
        choices=("qualification_test", "screening_test"),
        default="screening_test",
    )
    parser.add_argument("--image-manifest", type=Path, default=DEFAULT_IMAGE_MANIFEST)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--reference", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--confirm-provider-cost", action="store_true")
    return parser


def _write_json(path: Path, payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _plan_path(output_dir: Path, *, resume: bool) -> Path:
    suffix = ".resume-plan.json" if resume else ".plan.json"
    return output_dir.with_name(output_dir.name + suffix)


def _validate_resume(output_dir: Path, plan: dict[str, Any]) -> int:
    result_path = output_dir / "result.json"
    plan_path = output_dir / "plan.json"
    if not result_path.is_file() or not plan_path.is_file():
        raise FileNotFoundError("replay resume requires result.json and plan.json")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    original = json.loads(plan_path.read_text(encoding="utf-8"))
    locked = (
        "benchmark",
        "domain",
        "family",
        "evaluation_role",
        "selection_hash",
        "task_manifest_hash",
        "task_ids",
        "reference_label",
        "artifact_order",
        "artifact_hashes",
        "image_manifest_hash",
        "model",
        "temperature",
        "thinking",
    )
    mismatches = [field for field in locked if original.get(field) != plan.get(field)]
    if result.get("artifact_hashes") != plan["artifact_hashes"]:
        mismatches.append("result artifact_hashes")
    if mismatches:
        raise ValueError("resume preflight mismatch: " + ", ".join(mismatches))
    previous = int(result["repeat_count"])
    if previous != 3 or int(plan["repeat_count"]) != 5:
        raise ValueError("replay resume only supports extending 3 to 5 repeats")
    return previous


def main() -> None:
    args = _parser().parse_args()
    if args.repeats not in {3, 5}:
        raise ValueError("--repeats must be exactly 3 or 5")
    if args.resume and args.repeats != 5:
        raise ValueError("replay resume only supports extending 3 to 5 repeats")
    if not args.dry_run and not args.confirm_provider_cost:
        raise ValueError("provider-backed replay requires --confirm-provider-cost")
    manifest = args.manifest.resolve()
    portable = StableSplitCandidate.model_validate_json(
        manifest.read_text(encoding="utf-8")
    )
    if portable.benchmark != "skilllearnbench" or portable.domain != "skill_learning":
        raise ValueError("SkillLearn replay only supports SkillLearnBench")
    if portable.metadata.get("qualification_version") != "noise-screen-v1":
        raise ValueError("SkillLearn replay requires a noise-screen-v1 candidate")
    portable_tasks = select_candidate_evaluation_tasks(
        portable,
        evaluation_role=args.evaluation_role,
        family=args.family,
    )
    candidate = resolve_selection_candidate_paths(portable)
    tasks = select_candidate_evaluation_tasks(
        candidate,
        evaluation_role=args.evaluation_role,
        family=args.family,
    )
    image_manifest = args.image_manifest.resolve()
    if not image_manifest.is_file():
        raise FileNotFoundError(
            f"SkillLearn image manifest is missing: {image_manifest}"
        )
    image_payload = json.loads(image_manifest.read_text(encoding="utf-8"))
    if image_payload.get("all_ready") is not True:
        raise RuntimeError("SkillLearn image manifest is not ready")
    artifacts = parse_artifact_arguments(args.artifact)
    if args.reference not in artifacts:
        raise ValueError(f"reference artifact is missing: {args.reference}")
    output_dir = args.output_dir.resolve()
    task_ids = [task.task_id for task in tasks]
    plan: dict[str, Any] = {
        "schema_version": "rsebench.fixed-artifact-replay-plan.v1",
        "benchmark": candidate.benchmark,
        "domain": candidate.domain,
        "family": args.family,
        "evaluation_role": args.evaluation_role,
        "manifest": str(manifest),
        "selection_hash": candidate.selection_hash,
        "task_ids": task_ids,
        "task_manifest_hash": canonical_hash(
            [task.model_dump(mode="json") for task in portable_tasks]
        ),
        "reference_label": args.reference,
        "repeat_count": args.repeats,
        "order_policy": ORDER_POLICY,
        "artifact_order": list(artifacts),
        "artifact_paths": {label: str(path) for label, path in artifacts.items()},
        "artifact_hashes": {
            label: sha256_file(path) for label, path in artifacts.items()
        },
        "image_manifest_hash": sha256_file(image_manifest),
        "model": MODEL,
        "temperature": TEMPERATURE,
        "thinking": THINKING,
        "provider_calls": 0 if args.dry_run else None,
    }
    previous = _validate_resume(output_dir, plan) if args.resume else 0
    plan["resume"] = args.resume
    plan["previous_repeat_count"] = previous
    plan["additional_task_episode_count"] = (
        (args.repeats - previous) * len(artifacts) * len(task_ids)
    )
    plan_path = _plan_path(output_dir, resume=args.resume)
    if args.dry_run:
        _write_json(plan_path, plan)
        print(plan_path)
        return
    _write_json(plan_path, plan)
    executor = build_skilllearn_executor(output_dir=output_dir)
    result = evaluate_repeated_artifacts(
        executor=executor,
        artifacts=artifacts,
        reference_label=args.reference,
        clean_test=tasks,
        task_manifest_hash=plan["task_manifest_hash"],
        repeats=args.repeats,
        output_dir=output_dir,
        resume=args.resume,
    )
    if not args.resume:
        _write_json(output_dir / "plan.json", plan)
    print(output_dir)
    print(json.dumps(result.summaries, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
