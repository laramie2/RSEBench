"""DeepSeek API bridge that preserves EvoSkill's native evolution loop."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rsebench.agents.tool_agent import DeepSeekToolAgent, ToolAgentConfig
from rsebench.providers.deepseek import DeepSeekClient, DeepSeekConfig


LOCKED_MODEL = "deepseek-v4-flash"


class BridgeMessage(BaseModel):
    """Serializable result passed back through EvoSkill's Agent wrapper."""

    model_config = ConfigDict(extra="forbid")

    final_text: str
    turns: int
    tool_calls: int
    errors: list[str] = Field(default_factory=list)
    duration_ms: int


def build_options(
    *,
    system: str,
    schema: dict[str, Any],
    tools: list[str],
    project_root: str | Path,
    model: str | None = None,
    role: str = "executor",
    **_: Any,
) -> dict[str, Any]:
    """Build the dict consumed by the patched EvoSkill DeepSeek harness."""

    resolved_model = model or LOCKED_MODEL
    if resolved_model != LOCKED_MODEL:
        raise ValueError(f"EvoSkill DeepSeek adapter requires {LOCKED_MODEL}")
    return {
        "sdk": "deepseek_api",
        "model": LOCKED_MODEL,
        "system": system,
        "schema": schema,
        "tools": list(tools),
        "working_directory": str(Path(project_root).resolve()),
        "role": role,
    }


def _client_for(options: dict[str, Any]) -> DeepSeekClient:
    root = Path(options["working_directory"])
    return DeepSeekClient(
        DeepSeekConfig(
            model=LOCKED_MODEL,
            thinking="disabled",
            temperature=0,
            max_tokens=2048,
        ),
        cache_dir=root / ".evoskill" / "deepseek_cache",
    )


def _run_sync(options: dict[str, Any], query: str) -> BridgeMessage:
    schema = options.get("schema") or {}
    schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    instruction = (
        f"{query}\n\n"
        "After completing any necessary file operations, return only one JSON "
        f"object that validates against this schema: {schema_text}"
    )
    config = ToolAgentConfig(
        workspace_root=Path(options["working_directory"]),
        role=str(options.get("role") or "executor"),
        max_turns=12,
        command_timeout_seconds=60,
        allowed_executables=("python", "python3"),
    )
    started = time.monotonic()
    result = DeepSeekToolAgent(_client_for(options), config).run(
        instruction,
        system=str(options.get("system") or ""),
    )
    return BridgeMessage(
        final_text=result.final_text,
        turns=result.turns,
        tool_calls=result.tool_calls,
        errors=result.errors,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


async def execute_query(options: dict[str, Any], query: str) -> list[BridgeMessage]:
    """Run the shared bounded tool agent without blocking EvoSkill's event loop."""

    return [await asyncio.to_thread(_run_sync, options, query)]


def _extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("DeepSeek response did not contain a JSON object")
        try:
            payload = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"DeepSeek response contained invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("DeepSeek structured response must be a JSON object")
    return payload


def parse_response(
    messages: list[BridgeMessage], response_model: type[BaseModel]
) -> dict[str, Any]:
    """Translate a bridge result into EvoSkill's AgentTrace constructor fields."""

    if not messages:
        raise ValueError("DeepSeek bridge returned no messages")
    message = messages[-1]
    output: BaseModel | None = None
    parse_error: str | None = None
    raw: dict[str, Any] | None = None
    try:
        raw = _extract_json(message.final_text)
        output = response_model.model_validate(raw)
    except Exception as exc:
        parse_error = str(exc)
    return {
        "uuid": str(uuid.uuid4()),
        "session_id": "",
        "model": LOCKED_MODEL,
        "tools": [],
        "duration_ms": message.duration_ms,
        "total_cost_usd": 0.0,
        "num_turns": message.turns,
        "usage": {"tool_calls": message.tool_calls},
        "result": message.final_text,
        "is_error": bool(parse_error or message.errors),
        "output": output,
        "parse_error": parse_error,
        "raw_structured_output": raw,
        "messages": messages,
    }
