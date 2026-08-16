"""DeepSeek API action loop for Harbor task environments."""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from rsebench.agents.tool_agent import DeepSeekToolAgent, ToolAgentConfig
from rsebench.providers.deepseek import DeepSeekClient, DeepSeekConfig


RUN_COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "Run an argv command in the isolated Harbor task container.",
        "parameters": {
            "type": "object",
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional container working directory.",
                },
            },
            "required": ["argv"],
        },
    },
}


def _tool_argument_recovery_prompt(error: Exception) -> str | None:
    """Return the narrow retry used for malformed provider tool JSON."""

    if "returned invalid JSON arguments" not in str(error):
        return None
    return (
        "Your previous tool call arguments were malformed JSON. Retry the same "
        "step with one short single-line command and a valid JSON object. Do "
        "not combine multiple shell programs into one tool call."
    )


class HarborEnvironment(Protocol):
    async def exec(self, *, command: str, **kwargs: Any) -> Any: ...


class HarborAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(default="worker", min_length=1)
    max_turns: int = Field(default=30, ge=1, le=100)
    max_output_chars: int = Field(default=12_000, ge=1)
    allowed_executables: tuple[str, ...] = (
        "bash",
        "sh",
        "python",
        "python3",
        "ls",
        "find",
        "cat",
        "sed",
        "grep",
        "rg",
        "head",
        "tail",
        "pwd",
        "cp",
        "mv",
        "mkdir",
        "touch",
        "libreoffice",
        "soffice",
        "unzip",
        "zip",
    )


class HarborAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_text: str
    turns: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    errors: list[str] = Field(default_factory=list)
    trajectory: dict[str, Any]


class DeepSeekHarborAgent:
    def __init__(self, client: DeepSeekClient, config: HarborAgentConfig):
        self.client = client
        self.config = config

    def _command(self, arguments: dict[str, Any]) -> str:
        argv = arguments.get("argv")
        if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv
        ):
            raise ValueError("run_command argv must be a non-empty string list")
        executable = argv[0]
        if "/" in executable or executable not in self.config.allowed_executables:
            raise ValueError("run_command executable is not allowed")
        command = shlex.join(argv)
        cwd = arguments.get("cwd")
        if cwd is not None:
            if not isinstance(cwd, str) or not cwd.startswith("/") or ".." in cwd.split("/"):
                raise ValueError("run_command cwd must be an absolute contained path")
            command = f"cd -- {shlex.quote(cwd)} && {command}"
        return command

    def _truncate(self, text: str) -> str:
        if len(text) <= self.config.max_output_chars:
            return text
        return text[: self.config.max_output_chars] + "\n[truncated]"

    async def _execute(
        self, environment: HarborEnvironment, arguments: dict[str, Any]
    ) -> str:
        command = self._command(arguments)
        result = await environment.exec(command=command)
        output = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
        if stderr:
            output += stderr
        return_code = int(getattr(result, "return_code", 0) or 0)
        if return_code:
            output += f"\n[exit_code={return_code}]"
        return self._truncate(output.rstrip("\n"))

    async def run(
        self,
        instruction: str,
        environment: HarborEnvironment,
        *,
        system: str = "",
    ) -> HarborAgentResult:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": instruction})
        steps: list[dict[str, Any]] = [
            {"source": "user", "message": instruction, "tool_calls": []}
        ]
        input_tokens = output_tokens = call_count = 0
        errors: list[str] = []
        tool_argument_retries = 0
        for turn in range(1, self.config.max_turns + 1):
            try:
                response = await asyncio.to_thread(
                    self.client.complete,
                    messages,
                    tools=[RUN_COMMAND_TOOL],
                    tool_choice="auto",
                    role=self.config.role,
                )
            except RuntimeError as exc:
                recovery = _tool_argument_recovery_prompt(exc)
                if recovery is None or tool_argument_retries >= 2:
                    raise
                tool_argument_retries += 1
                messages.append({"role": "user", "content": recovery})
                steps.append(
                    {
                        "source": "user",
                        "message": recovery,
                        "tool_calls": [],
                        "kind": "provider_protocol_recovery",
                    }
                )
                continue
            input_tokens += int(response.usage.get("prompt_tokens", 0) or 0)
            output_tokens += int(response.usage.get("completion_tokens", 0) or 0)
            step: dict[str, Any] = {
                "source": "agent",
                "message": response.content or "(tool use)",
                "tool_calls": [],
            }
            if not response.tool_calls:
                steps.append(step)
                return HarborAgentResult(
                    final_text=response.content,
                    turns=turn,
                    tool_calls=call_count,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    errors=errors,
                    trajectory={
                        "schema_version": "1.0",
                        "agent": {"name": "deepseek-api", "model_name": "deepseek-v4-flash"},
                        "steps": steps,
                    },
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
                                "arguments": json.dumps(item.arguments),
                            },
                        }
                        for item in response.tool_calls
                    ],
                }
            )
            observations: list[dict[str, str]] = []
            for item in response.tool_calls:
                call_count += 1
                step["tool_calls"].append(
                    {
                        "id": item.id,
                        "function_name": item.name,
                        "arguments": item.arguments,
                    }
                )
                try:
                    if item.name != "run_command":
                        raise ValueError(f"unknown tool: {item.name}")
                    observation = await self._execute(environment, item.arguments)
                except Exception as exc:
                    observation = f"tool_error: {exc}"
                    errors.append(observation)
                observations.append({"content": observation})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.id,
                        "content": observation,
                    }
                )
            step["observation"] = {"results": observations}
            steps.append(step)
        raise RuntimeError(
            f"DeepSeek Harbor agent exceeded max_turns={self.config.max_turns}"
        )


class DeepSeekSandboxRunner:
    """FederatedSkill cloud-merger runner using a contained local tool loop.

    The callable matches FederatedSkill's ``AgentRunner`` protocol. Credentials
    remain process environment state; the per-call ``env`` mapping is accepted
    for protocol compatibility but is never persisted or copied into artifacts.
    """

    def __init__(
        self,
        client_factory: Callable[[Path], DeepSeekClient] | None = None,
    ) -> None:
        self._client_factory = client_factory or self._default_client

    @staticmethod
    def _default_client(cache_dir: Path) -> DeepSeekClient:
        return DeepSeekClient(
            DeepSeekConfig(
                model="deepseek-v4-flash",
                thinking="disabled",
                temperature=0,
                max_tokens=4096,
            ),
            cache_dir=cache_dir,
        )

    def __call__(
        self,
        *,
        sandbox_dir: Path,
        prompt: str,
        model_name: str,
        max_turns: int,
        wall_clock_sec: int,
        env: dict[str, str] | None = None,
    ) -> None:
        del env
        if model_name != "deepseek-v4-flash":
            raise ValueError("DeepSeekSandboxRunner requires deepseek-v4-flash")
        root = Path(sandbox_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        client = self._client_factory(root / ".rsebench-cache")
        agent = DeepSeekToolAgent(
            client,
            ToolAgentConfig(
                workspace_root=root,
                role="merger",
                max_turns=max_turns,
                command_timeout_seconds=max(1.0, min(float(wall_clock_sec), 600.0)),
                max_output_chars=12_000,
                allowed_executables=("bash", "sh", "python", "python3"),
            ),
        )
        result = agent.run(
            prompt,
            system=(
                "You are the cloud skill merger. Work only inside the provided "
                "sandbox, follow the merge procedure exactly, validate edits, and "
                "write the requested completion marker before finishing."
            ),
        )
        (root / "deepseek-merger.json").write_text(
            json.dumps(
                {
                    "model": "deepseek-v4-flash",
                    "thinking": "disabled",
                    "role": "merger",
                    "turns": result.turns,
                    "tool_calls": result.tool_calls,
                    "errors": result.errors,
                    "final_text": result.final_text,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
