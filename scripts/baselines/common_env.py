"""Secret-safe DeepSeek environment mappings for native baseline clients."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"

_ROLES = {
    "trace2skill": {"executor", "analysis", "optimizer"},
    "skillopt": {"target", "optimizer"},
    "skillgrad": {"executor", "diagnoser", "momentum", "patcher"},
    "evoskill": {"executor", "proposer", "evaluator"},
    "skills_coach": {"generator", "optimizer", "executor", "judge"},
    "skillflow": {"worker", "patcher"},
    "federatedskill": {"worker", "patcher", "merger"},
}


def _credential_env_path() -> Path:
    local = PROJECT_ROOT / ".env"
    if local.is_file() and str(dotenv_values(local).get("DEEPSEEK_API_KEY") or "").strip():
        return local
    completed = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    common = Path(completed.stdout.strip())
    if not common.is_absolute():
        common = (PROJECT_ROOT / common).resolve()
    return common.parent / ".env"


def load_deepseek_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        key = str(
            dotenv_values(_credential_env_path()).get("DEEPSEEK_API_KEY") or ""
        ).strip()
        if key:
            os.environ["DEEPSEEK_API_KEY"] = key
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is empty")
    return key


def methods_root() -> Path:
    load_dotenv(_credential_env_path())
    configured = os.environ.get("RSEBENCH_METHODS_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    return _credential_env_path().parent / "methods/external"


def deepseek_role_env(
    method: str, role: str, *, api_key: str | None = None
) -> dict[str, str]:
    if method not in _ROLES or role not in _ROLES[method]:
        raise ValueError(f"unsupported role for {method}: {role}")
    key = api_key or load_deepseek_key()
    common = {
        "RSEBENCH_MODEL": MODEL,
        "RSEBENCH_THINKING": "disabled",
    }
    if method == "trace2skill":
        return {
            **common,
            "OPENAI_API_KEY": key,
            "OPENAI_BASE_URL": BASE_URL,
        }
    if method == "skillopt":
        prefix = role.upper()
        return {
            **common,
            f"{prefix}_OPENAI_COMPATIBLE_API_KEY": key,
            f"{prefix}_OPENAI_COMPATIBLE_BASE_URL": BASE_URL,
            f"{prefix}_OPENAI_COMPATIBLE_MODEL": MODEL,
            f"{prefix}_OPENAI_COMPATIBLE_MAX_TOKENS": "2048",
            f"{prefix}_OPENAI_COMPATIBLE_TEMPERATURE": "0",
            f"{prefix}_OPENAI_COMPATIBLE_THINKING": "disabled",
        }
    if method in {"evoskill", "skills_coach", "skillflow", "federatedskill"}:
        inherited = os.environ.get("PYTHONPATH", "").strip()
        pythonpath = str(PROJECT_ROOT / "src")
        if inherited:
            pythonpath = os.pathsep.join((pythonpath, inherited))
        return {
            **common,
            "DEEPSEEK_API_KEY": key,
            "PYTHONPATH": pythonpath,
        }
    return {
        **common,
        "AZURE_OPENAI_API_KEY": key,
        "AZURE_OPENAI_ENDPOINT": BASE_URL,
    }


def combined_method_env(method: str) -> dict[str, str]:
    key = load_deepseek_key()
    env = dict(os.environ)
    for role in sorted(_ROLES[method]):
        env.update(deepseek_role_env(method, role, api_key=key))
    return env


def _redact(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


def write_smoke_result(
    output: Path | str,
    *,
    method: str,
    level: str,
    status: str,
    detail: str,
    evidence: dict[str, Any],
) -> Path:
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    secret = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    payload = _redact(
        {
            "method": method,
            "level": level,
            "status": status,
            "model": MODEL,
            "detail": detail,
            "evidence": evidence,
        },
        secret,
    )
    path = target / "result.json"
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path
