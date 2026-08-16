#!/usr/bin/env python3
"""Run one clean SkillLearn family qualification with fixed budgets."""

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
    PROJECT_ROOT
    / "outputs/preflight/clean-qualification-v1/skilllearn/image_manifest.json"
)
METHOD_SEEDS = (20260813, 20260814, 20260815)
RUNTIME = {
    "max_tool_turns": 16,
    "max_completion_tokens": 4096,
    "evolution_rounds": 2,
    "require_prebuilt_images": True,
}
OFFLINE_VERIFIER_PACKAGES = [
    "pytest==8.4.1",
    "pytest-json-ctrf==0.3.5",
]
MAX_COMMAND_TIMEOUT_SECONDS = 1800


from rsebench.core1.dataset import resolve_clean_split_paths  # noqa: E402
from rsebench.evolution.clean_bridge import build_clean_runtime_split  # noqa: E402
from rsebench.evolution.clean_contracts import CleanQualificationPolicy  # noqa: E402
from rsebench.evolution.clean_runner import CleanEvolutionRunner  # noqa: E402
from rsebench.evolution.pairs import build_clean_arm_manifest  # noqa: E402
from rsebench.evolution.skilllearn_executor import (  # noqa: E402
    DockerSkillLearnBackend,
    SkillLearnExecutor,
)
from rsebench.hashing import sha256_file, sha256_tree  # noqa: E402
from rsebench.experiments.runtime import load_runtime_identity  # noqa: E402
from rsebench.experiments.preflight import (  # noqa: E402
    SUPPORTED_QUALIFICATION_VERSIONS,
)
from rsebench.providers.deepseek import DeepSeekClient  # noqa: E402
from rsebench.selection.clean_view import load_clean_runtime_view  # noqa: E402
from scripts.baselines.common_env import methods_root  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seed-skill", type=Path, required=True)
    parser.add_argument("--method-seed", type=int, choices=METHOD_SEEDS, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--image-manifest", type=Path, default=DEFAULT_IMAGE_MANIFEST)
    parser.add_argument("--family")
    parser.add_argument("--command-timeout-seconds", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != encoded:
        raise FileExistsError(f"different SkillLearn dry run already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _resolve_verifier_wheelhouse(
    image_manifest: Path,
    payload: dict[str, Any],
) -> tuple[Path | None, dict[str, Any] | None]:
    verifier = payload.get("verifier")
    if verifier is None:
        return None, None
    if not isinstance(verifier, dict) or verifier.get("mode") != "offline_pytest":
        raise ValueError("unsupported SkillLearn verifier manifest mode")
    if verifier.get("packages") != OFFLINE_VERIFIER_PACKAGES:
        raise ValueError("SkillLearn verifier package pins differ from formal settings")
    raw = verifier.get("wheelhouse")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("SkillLearn verifier wheelhouse locator is missing")
    locator = Path(raw)
    if locator.is_absolute() or ".." in locator.parts:
        raise ValueError("SkillLearn verifier wheelhouse must be manifest-relative")
    manifest_root = image_manifest.resolve().parent
    wheelhouse = (manifest_root / locator).resolve()
    try:
        wheelhouse.relative_to(manifest_root)
    except ValueError as exc:
        raise ValueError("SkillLearn verifier wheelhouse escapes manifest root") from exc
    if not wheelhouse.is_dir():
        raise FileNotFoundError(
            f"SkillLearn verifier wheelhouse is missing: {wheelhouse}"
        )
    expected_hash = str(verifier.get("wheelhouse_hash") or "")
    actual_hash = sha256_tree(wheelhouse)
    if actual_hash != expected_hash:
        raise RuntimeError(
            "SkillLearn verifier wheelhouse hash differs: "
            f"{actual_hash} != {expected_hash}"
        )
    identity = {
        "mode": "offline_pytest",
        "packages": list(OFFLINE_VERIFIER_PACKAGES),
        "wheelhouse_hash": actual_hash,
    }
    return wheelhouse, identity


def run_manifest(
    manifest: Path,
    *,
    seed_skill: Path,
    method_seed: int,
    output_root: Path,
    image_manifest: Path = DEFAULT_IMAGE_MANIFEST,
    family: str | None = None,
    command_timeout_seconds: int | None = None,
    dry_run: bool = False,
) -> Path:
    if command_timeout_seconds is not None and not (
        1 <= command_timeout_seconds <= MAX_COMMAND_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "SkillLearn command timeout must be between 1 and "
            f"{MAX_COMMAND_TIMEOUT_SECONDS} seconds"
        )
    if method_seed not in METHOD_SEEDS:
        raise ValueError(f"unsupported formal method seed: {method_seed}")
    portable = load_clean_runtime_view(manifest, family=family)
    if portable.benchmark != "skilllearnbench" or portable.domain != "skill_learning":
        raise ValueError("clean SkillLearn launcher only supports SkillLearnBench")
    sizes = (
        len(portable.train),
        len(portable.validation),
        len(portable.clean_test),
    )
    validation_only = portable.metadata.get("evaluation_mode") == "validation_only"
    if sizes not in {(2, 1, 2), (2, 1, 3)} and not (
        sizes == (2, 1, 0) and validation_only
    ):
        raise ValueError("clean SkillLearn qualification requires 2/1/2-or-3 or 2/1/0 validation-only")
    if portable.metadata.get("feedback_mode") != "self":
        raise ValueError("clean SkillLearn qualification requires self feedback")
    if portable.metadata.get("runtime") != RUNTIME:
        raise ValueError("SkillLearn runtime metadata differs from formal settings")
    qualification_version = str(
        portable.metadata.get("qualification_version") or "clean-qualification-v1"
    )
    if qualification_version not in SUPPORTED_QUALIFICATION_VERSIONS:
        raise ValueError(
            f"unsupported SkillLearn qualification version: {qualification_version}"
        )
    identity, attempt = load_runtime_identity(
        required=(
            qualification_version in {"clean-qualification-v2", "noise-screen-v1"}
            and not dry_run
        ),
        benchmark=portable.benchmark,
        method_seed=method_seed,
    )
    family = str(portable.metadata.get("task_family") or "").strip()
    if not family:
        raise ValueError("SkillLearn manifest has no task_family")
    family_values = {
        str(task.metadata.get("task_family") or "")
        for task in portable.train + portable.validation + portable.clean_test
    }
    if family_values != {family}:
        raise ValueError("SkillLearn manifest crosses family boundaries")
    seed_skill = seed_skill.resolve()
    if not seed_skill.is_file():
        raise FileNotFoundError(f"SkillLearn seed skill is missing: {seed_skill}")
    if not image_manifest.is_file():
        raise FileNotFoundError(
            f"SkillLearn image manifest is missing: {image_manifest}"
        )
    image_payload = json.loads(image_manifest.read_text(encoding="utf-8"))
    if image_payload.get("all_ready") is not True:
        raise RuntimeError("SkillLearn image manifest is not ready")
    verifier_wheelhouse, verifier_identity = _resolve_verifier_wheelhouse(
        image_manifest,
        image_payload,
    )

    external_methods = methods_root()
    split = resolve_clean_split_paths(
        portable,
        project_root=PROJECT_ROOT,
        data_root=SHARED_ROOT / "data",
        methods_root=external_methods,
    )
    parameters = {
        "qualification_version": qualification_version,
        "family": family,
        "model": "deepseek-v4-flash",
        "thinking": "disabled",
        "temperature": 0,
        "feedback_mode": "self",
        "train_tasks": 2,
        "validation_tasks": 1,
        "clean_test_tasks": len(split.clean_test),
        "runtime": RUNTIME,
        "image_manifest_hash": sha256_file(image_manifest),
    }
    if verifier_identity is not None:
        parameters["verifier"] = verifier_identity
    if command_timeout_seconds is not None:
        parameters["command_timeout_seconds"] = command_timeout_seconds
    if dry_run:
        runtime_split = build_clean_runtime_split(split)
        seed_hash = sha256_file(seed_skill)
        arm = build_clean_arm_manifest(
            runtime_split,
            method="skilllearn_self_feedback",
            method_seed=method_seed,
            seed_skill_hash=seed_hash,
            parameters=parameters,
        )
        run_dir = output_root.resolve() / family / str(method_seed) / "dry-run"
        _write_json(
            run_dir / "dry_run.json",
            {
                "schema_version": "rsebench.clean-skilllearn-dry-run.v1",
                "family": family,
                "method_seed": method_seed,
                "split_source_hash": split.source_hash,
                "seed_skill_hash": seed_hash,
                "task_counts": {
                    "train": 2,
                    "validation": 1,
                    "clean_test": len(split.clean_test),
                },
                "arm_manifest": arm.model_dump(mode="json"),
                "parameters": parameters,
                "provider_calls": 0,
                "token_events": 0,
                "identity": identity.model_dump(mode="json") if identity else None,
            },
        )
        return run_dir

    client = DeepSeekClient.from_yaml(PROVIDER_CONFIG)
    backend_kwargs: dict[str, Any] = {
        "client": client,
        "max_turns": 16,
        "require_prebuilt": True,
        "verifier_wheelhouse": verifier_wheelhouse,
    }
    if command_timeout_seconds is not None:
        backend_kwargs["command_timeout"] = command_timeout_seconds
    backend = DockerSkillLearnBackend(
        **backend_kwargs,
    )
    executor = SkillLearnExecutor(
        client=client,
        backend=backend,
        evidence_spec=None,
        feedback_mode="self",
        ledger_dir=output_root / "pending-token-ledger",
        run_id="pending",
    )
    result = CleanEvolutionRunner(executor).run(
        method="skilllearn_self_feedback",
        split=split,
        seed_skill_path=seed_skill,
        method_seed=method_seed,
        parameters=parameters,
        output_root=output_root.resolve() / family / str(method_seed),
        policy=CleanQualificationPolicy(),
        identity=identity,
        attempt=attempt,
    )
    return Path(result.run_dir)


def main() -> None:
    args = build_parser().parse_args()
    run_dir = run_manifest(
        args.manifest,
        seed_skill=args.seed_skill,
        method_seed=args.method_seed,
        output_root=args.output_root,
        image_manifest=args.image_manifest,
        family=args.family,
        command_timeout_seconds=args.command_timeout_seconds,
        dry_run=args.dry_run,
    )
    print(run_dir)


if __name__ == "__main__":
    main()
