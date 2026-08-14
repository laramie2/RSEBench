"""Exact lower-bound audit for legacy runs without canonical token events."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


AUDIT_SCHEMA_VERSION = "rsebench.legacy-token-audit.v1"


def _empty_tokens() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"malformed legacy JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"legacy JSON must contain an object: {path}")
    return payload


def _validated_usage(
    payload: Mapping[str, Any], path: Path, *, require_calls: bool
) -> tuple[int, dict[str, int]]:
    try:
        calls = int(payload.get("calls", 1))
        prompt = int(payload["prompt_tokens"])
        completion = int(payload["completion_tokens"])
        total = int(payload["total_tokens"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed observable usage: {path}") from exc
    if require_calls and "calls" not in payload:
        raise ValueError(f"observable SkillOpt usage has no call count: {path}")
    if min(calls, prompt, completion, total) < 0 or total != prompt + completion:
        raise ValueError(f"inconsistent observable usage: {path}")
    return calls, {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _add_tokens(target: dict[str, int], source: Mapping[str, int]) -> None:
    for name in target:
        target[name] += int(source[name])


def scan_skillopt_training_totals(project_root: Path | str) -> dict[str, Any]:
    """Sum only clean/noisy native-training `_total` records."""

    root = Path(project_root).resolve()
    calls = 0
    tokens = _empty_tokens()
    files: list[str] = []
    for path in sorted(root.rglob("native_train/summary.json")):
        if path.parent.parent.name not in {"clean", "noisy"}:
            continue
        payload = _read_json(path)
        token_summary = payload.get("token_summary")
        if token_summary is None:
            continue
        if not isinstance(token_summary, dict) or not isinstance(
            token_summary.get("_total"), dict
        ):
            raise ValueError(f"malformed SkillOpt token summary: {path}")
        file_calls, file_tokens = _validated_usage(
            token_summary["_total"], path, require_calls=True
        )
        calls += file_calls
        _add_tokens(tokens, file_tokens)
        files.append(str(path.resolve()))
    return {"calls": calls, "tokens": tokens, "files": files}


def scan_deepseek_cache(project_root: Path | str) -> dict[str, Any]:
    """Count each resolved legacy DeepSeek response-cache object once."""

    root = Path(project_root).resolve()
    calls = 0
    tokens = _empty_tokens()
    files: list[str] = []
    response_hashes: list[str] = []
    seen_paths: set[Path] = set()
    for cache_root in sorted(root.glob("**/cache/model")):
        if not cache_root.is_dir():
            continue
        for path in sorted(cache_root.glob("*.json")):
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            payload = _read_json(path)
            usage = payload.get("usage")
            if usage is None:
                continue
            if not isinstance(usage, dict):
                raise ValueError(f"malformed DeepSeek cache usage: {path}")
            file_calls, file_tokens = _validated_usage(usage, path, require_calls=False)
            calls += file_calls
            _add_tokens(tokens, file_tokens)
            encoded = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            response_hashes.append(hashlib.sha256(encoded).hexdigest())
            files.append(str(resolved))
    return {
        "calls": calls,
        "tokens": tokens,
        "context": "unknown",
        "files": files,
        "response_hashes": response_hashes,
    }


def scan_unobservable_evaluations(project_root: Path | str) -> dict[str, Any]:
    """Count legacy evaluation conversations whose usage was not persisted."""

    root = Path(project_root).resolve()
    files: list[str] = []
    for summary_path in sorted(root.rglob("native_eval/eval_summary.json")):
        payload = _read_json(summary_path)
        if payload.get("token_summary") is not None:
            continue
        native_eval = summary_path.parent
        if (native_eval.parent / "reused.json").is_file():
            continue
        for conversation in sorted(
            native_eval.glob("predictions/**/conversation.json")
        ):
            files.append(str(conversation.resolve()))
    return {"calls": len(files), "files": files}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _render_report(summary: Mapping[str, Any]) -> str:
    billed = summary["billed_tokens"]
    lines = [
        "# Legacy Token Usage Audit",
        "",
        "This report is an exact lower bound derived only from persisted usage fields.",
        "Legacy calls without persisted usage remain unobservable.",
        "",
        f"Observed calls: {summary['observed_calls']}",
        f"Unobservable calls: {summary['unobservable_calls']}",
        f"Observed coverage: {summary['observed_coverage']:.4f}",
        "",
        "| View | Prompt | Completion | Total |",
        "|---|---:|---:|---:|",
        f"| Billed lower bound | {billed['prompt_tokens']} | "
        f"{billed['completion_tokens']} | {billed['total_tokens']} |",
        "",
    ]
    return "\n".join(lines)


def audit_historical_usage(
    project_root: Path | str, output_dir: Path | str
) -> dict[str, Any]:
    """Audit exact observable legacy usage and persist an immutable summary."""

    skillopt = scan_skillopt_training_totals(project_root)
    cache = scan_deepseek_cache(project_root)
    unobservable = scan_unobservable_evaluations(project_root)
    billed = _empty_tokens()
    _add_tokens(billed, skillopt["tokens"])
    _add_tokens(billed, cache["tokens"])
    observed_calls = int(skillopt["calls"]) + int(cache["calls"])
    unobservable_calls = int(unobservable["calls"])
    attempted = observed_calls + unobservable_calls
    summary: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "exact_lower_bound": True,
        "observed_calls": observed_calls,
        "unobservable_calls": unobservable_calls,
        "attempted_calls_lower_bound": attempted,
        "observed_coverage": observed_calls / attempted if attempted else 1.0,
        "billed_tokens": billed,
        "logical_tokens_lower_bound": dict(billed),
        "sources": {
            "skillopt_training": {
                "calls": skillopt["calls"],
                **skillopt["tokens"],
                "context": "arm_only",
            },
            "legacy_deepseek_cache": {
                "calls": cache["calls"],
                **cache["tokens"],
                "context": cache["context"],
            },
            "unobservable_evaluation": {
                "calls": unobservable_calls,
                "context": "evaluation_conversation",
            },
        },
        "source_file_counts": {
            "skillopt_training_summaries": len(skillopt["files"]),
            "deepseek_cache_files": len(cache["files"]),
            "unobservable_evaluation_conversations": len(unobservable["files"]),
        },
    }
    destination = Path(output_dir)
    _atomic_write(
        destination / "summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write(destination / "report.md", _render_report(summary))
    return summary
