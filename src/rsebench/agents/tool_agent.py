"""A bounded local tool loop driven through the DeepSeek API."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rsebench.providers.deepseek import DeepSeekClient


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files below a workspace-relative directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_text",
            "description": "Read a UTF-8 text file below the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_text",
            "description": "Write UTF-8 text below the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run an allowlisted argv command below the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "cwd": {"type": "string", "default": "."},
                },
                "required": ["argv"],
            },
        },
    },
]


class ToolAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_root: Path
    max_turns: int = Field(default=12, ge=1, le=100)
    command_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    max_output_chars: int = Field(default=12_000, ge=1)
    allowed_executables: tuple[str, ...] = (
        "bash",
        "python",
        "python3",
        "sh",
    )


class ToolAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_text: str
    turns: int
    tool_calls: int
    errors: list[str] = Field(default_factory=list)


class DeepSeekToolAgent:
    """Execute a minimal, path-contained API tool loop."""

    def __init__(self, client: DeepSeekClient, config: ToolAgentConfig):
        self.client = client
        self.config = config
        self.workspace_root = config.workspace_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def _contained(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            raise ValueError("path is outside workspace")
        candidate = (self.workspace_root / path).resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("path is outside workspace") from exc
        return candidate

    def _truncate(self, value: str) -> str:
        if len(value) <= self.config.max_output_chars:
            return value
        return value[: self.config.max_output_chars] + "\n[truncated]"

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "list_files":
            root = self._contained(str(arguments.get("path", ".")))
            if not root.is_dir():
                raise ValueError("list_files path is not a directory")
            files = sorted(
                str(path.relative_to(self.workspace_root))
                for path in root.rglob("*")
                if path.is_file()
            )
            return self._truncate("\n".join(files))

        if name == "read_text":
            path = self._contained(str(arguments["path"]))
            if not path.is_file():
                raise ValueError("read_text path is not a file")
            return self._truncate(path.read_text(encoding="utf-8"))

        if name == "write_text":
            path = self._contained(str(arguments["path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            content = arguments["content"]
            if not isinstance(content, str):
                raise ValueError("write_text content must be a string")
            path.write_text(content, encoding="utf-8")
            return f"wrote {path.relative_to(self.workspace_root)}"

        if name == "run_command":
            argv = arguments.get("argv")
            if not isinstance(argv, list) or not argv or not all(
                isinstance(item, str) and item for item in argv
            ):
                raise ValueError("run_command argv must be a non-empty string list")
            executable = argv[0]
            if "/" in executable or executable not in self.config.allowed_executables:
                raise ValueError("run_command executable is not allowed")
            cwd = self._contained(str(arguments.get("cwd", ".")))
            if not cwd.is_dir():
                raise ValueError("run_command cwd is not a directory")
            completed = subprocess.run(
                argv,
                cwd=cwd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.config.command_timeout_seconds,
                check=False,
            )
            output = completed.stdout
            if completed.stderr:
                output += completed.stderr
            if completed.returncode:
                output += f"\n[exit_code={completed.returncode}]"
            return self._truncate(output.rstrip("\n"))

        raise ValueError(f"unknown tool: {name}")

    def run(self, instruction: str, system: str = "") -> ToolAgentResult:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": instruction})
        errors: list[str] = []
        call_count = 0
        for turn in range(1, self.config.max_turns + 1):
            response = self.client.complete(
                messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                role="executor",
            )
            if not response.tool_calls:
                return ToolAgentResult(
                    final_text=response.content,
                    turns=turn,
                    tool_calls=call_count,
                    errors=errors,
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or None,
                    "tool_calls": [
                        {
                            "id": item.id,
                            "type": "function",
                            "function": {
                                "name": item.name,
                                "arguments": json.dumps(
                                    item.arguments, ensure_ascii=False, sort_keys=True
                                ),
                            },
                        }
                        for item in response.tool_calls
                    ],
                }
            )
            for item in response.tool_calls:
                call_count += 1
                try:
                    observation = self.execute_tool(item.name, item.arguments)
                except Exception as exc:  # tool errors are recoverable observations
                    observation = f"tool_error: {exc}"
                    errors.append(observation)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.id,
                        "content": observation,
                    }
                )
        raise RuntimeError(
            f"DeepSeek tool agent exceeded max_turns={self.config.max_turns}"
        )
