from pathlib import Path

import pytest

from rsebench.agents.tool_agent import (
    DeepSeekToolAgent,
    ToolAgentConfig,
)
from rsebench.providers.contracts import ToolCall
from rsebench.providers.deepseek import ModelResponse


class ScriptedClient:
    def __init__(self, responses: list[ModelResponse]):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return next(self.responses)


def _tool(name: str, arguments: dict, call_id: str = "call-1") -> ModelResponse:
    return ModelResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


def test_read_rejects_path_escape(tmp_path: Path):
    agent = DeepSeekToolAgent(
        ScriptedClient([]), ToolAgentConfig(workspace_root=tmp_path)
    )

    with pytest.raises(ValueError, match="outside workspace"):
        agent.execute_tool("read_text", {"path": "../secret"})


def test_read_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(outside)
    agent = DeepSeekToolAgent(
        ScriptedClient([]), ToolAgentConfig(workspace_root=tmp_path)
    )

    with pytest.raises(ValueError, match="outside workspace"):
        agent.execute_tool("read_text", {"path": "link.txt"})


def test_agent_executes_tool_then_returns_final_text(tmp_path: Path):
    client = ScriptedClient(
        [
            _tool("write_text", {"path": "x.txt", "content": "ok"}),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = DeepSeekToolAgent(client, ToolAgentConfig(workspace_root=tmp_path))

    result = agent.run("write x")

    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "ok"
    assert result.final_text == "done"
    assert result.turns == 2
    assert result.tool_calls == 1
    assert client.calls[0][1]["role"] == "executor"


def test_agent_uses_configured_role_for_cache_isolation(tmp_path: Path):
    client = ScriptedClient([ModelResponse(content="done", finish_reason="stop")])
    agent = DeepSeekToolAgent(
        client,
        ToolAgentConfig(workspace_root=tmp_path, role="optimizer"),
    )

    agent.run("improve it")

    assert client.calls[0][1]["role"] == "optimizer"


def test_run_command_uses_argv_and_truncates_output(tmp_path: Path):
    agent = DeepSeekToolAgent(
        ScriptedClient([]),
        ToolAgentConfig(workspace_root=tmp_path, max_output_chars=5),
    )

    output = agent.execute_tool(
        "run_command",
        {"argv": ["python", "-c", "print('abcdefgh')"], "cwd": "."},
    )

    assert output == "abcde\n[truncated]"


def test_run_command_rejects_unlisted_executable(tmp_path: Path):
    agent = DeepSeekToolAgent(
        ScriptedClient([]), ToolAgentConfig(workspace_root=tmp_path)
    )

    with pytest.raises(ValueError, match="executable is not allowed"):
        agent.execute_tool("run_command", {"argv": ["curl", "example.com"]})
