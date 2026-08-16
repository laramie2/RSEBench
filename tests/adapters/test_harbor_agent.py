import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rsebench.adapters.harbor_agent import (
    DeepSeekHarborAgent,
    DeepSeekSandboxRunner,
    HarborAgentConfig,
)
from rsebench.providers.contracts import ToolCall
from rsebench.providers.deepseek import ModelResponse


class ScriptedClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeEnvironment:
    def __init__(self):
        self.commands = []

    async def exec(self, *, command, **kwargs):
        self.commands.append((command, kwargs))
        return SimpleNamespace(return_code=0, stdout="ok\n", stderr="")


def test_harbor_agent_executes_terminal_tool_then_finishes():
    client = ScriptedClient(
        [
            ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="run_command",
                        arguments={"argv": ["python", "-c", "print('ok')"]},
                    )
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 2},
            ),
            ModelResponse(
                content="done",
                usage={"prompt_tokens": 5, "completion_tokens": 1},
            ),
        ]
    )
    environment = FakeEnvironment()
    agent = DeepSeekHarborAgent(client, HarborAgentConfig(max_turns=3))

    result = asyncio.run(agent.run("do it", environment))

    assert environment.commands[0][0] == "python -c 'print('\"'\"'ok'\"'\"')'"
    assert result.final_text == "done"
    assert result.input_tokens == 15
    assert result.output_tokens == 3
    assert result.trajectory["steps"][1]["tool_calls"][0]["function_name"] == "run_command"
    assert result.trajectory["steps"][1]["observation"]["results"][0]["content"] == "ok"


def test_harbor_agent_uses_merger_role():
    client = ScriptedClient([ModelResponse(content="merged")])
    agent = DeepSeekHarborAgent(client, HarborAgentConfig(role="merger"))

    asyncio.run(agent.run("merge", FakeEnvironment()))

    assert client.calls[0][1]["role"] == "merger"


def test_harbor_agent_retries_malformed_tool_json_with_a_bounded_prompt():
    client = ScriptedClient(
        [
            RuntimeError(
                "DeepSeek tool call 'run_command' returned invalid JSON arguments"
            ),
            ModelResponse(content="done"),
        ]
    )
    agent = DeepSeekHarborAgent(client, HarborAgentConfig(max_turns=3))

    result = asyncio.run(agent.run("do it", FakeEnvironment()))

    assert result.final_text == "done"
    assert len(client.calls) == 2
    retry_message = client.calls[1][0][-1]
    assert retry_message["role"] == "user"
    assert "one short single-line command" in retry_message["content"]
    assert result.trajectory["steps"][1]["kind"] == "provider_protocol_recovery"


def test_harbor_agent_stops_after_two_malformed_tool_json_retries():
    malformed = RuntimeError(
        "DeepSeek tool call 'run_command' returned invalid JSON arguments"
    )
    client = ScriptedClient([malformed, malformed, malformed])
    agent = DeepSeekHarborAgent(client, HarborAgentConfig(max_turns=4))

    with pytest.raises(RuntimeError, match="invalid JSON arguments"):
        asyncio.run(agent.run("do it", FakeEnvironment()))

    assert len(client.calls) == 3


def test_sandbox_runner_uses_merger_role_and_writes_audit_log(tmp_path: Path):
    client = ScriptedClient(
        [
            ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="write_text",
                        arguments={"path": "DONE.txt", "content": "merged"},
                    )
                ],
            ),
            ModelResponse(content="complete"),
        ]
    )
    runner = DeepSeekSandboxRunner(client_factory=lambda _: client)

    runner(
        sandbox_dir=tmp_path,
        prompt="merge the skill library",
        model_name="deepseek-v4-flash",
        max_turns=3,
        wall_clock_sec=10,
        env={"DEEPSEEK_API_KEY": "must-not-be-written"},
    )

    assert (tmp_path / "DONE.txt").read_text(encoding="utf-8") == "merged"
    assert client.calls[0][1]["role"] == "merger"
    audit = json.loads((tmp_path / "deepseek-merger.json").read_text(encoding="utf-8"))
    assert audit["model"] == "deepseek-v4-flash"
    assert audit["role"] == "merger"
    assert "must-not-be-written" not in json.dumps(audit)


def test_sandbox_runner_rejects_other_models(tmp_path: Path):
    runner = DeepSeekSandboxRunner(client_factory=lambda _: ScriptedClient([]))

    with pytest.raises(ValueError, match="requires deepseek-v4-flash"):
        runner(
            sandbox_dir=tmp_path,
            prompt="merge",
            model_name="other-model",
            max_turns=1,
            wall_clock_sec=1,
            env=None,
        )
