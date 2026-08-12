from pathlib import Path
from types import SimpleNamespace

import rsebench.providers.deepseek as deepseek
from rsebench.providers.deepseek import DeepSeekClient, DeepSeekConfig


READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read_text",
        "description": "Read a text file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}


def _client_with_tool_call(tmp_path: Path, monkeypatch) -> DeepSeekClient:
    class FakeCompletions:
        def create(self, **kwargs):
            tool_call = SimpleNamespace(
                id="call-1",
                type="function",
                function=SimpleNamespace(
                    name="read_text", arguments='{"path":"note.txt"}'
                ),
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=None, tool_calls=[tool_call]),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
                model="deepseek-v4-flash",
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(deepseek, "OpenAI", FakeOpenAI)
    return DeepSeekClient(DeepSeekConfig(thinking="disabled"), tmp_path)


def test_tool_call_response_is_normalized(tmp_path: Path, monkeypatch):
    client = _client_with_tool_call(tmp_path, monkeypatch)

    response = client.complete(
        [{"role": "user", "content": "read it"}],
        tools=[READ_TOOL],
        role="executor",
    )

    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].name == "read_text"
    assert response.tool_calls[0].arguments == {"path": "note.txt"}


def test_cache_key_isolated_by_role_and_tools(tmp_path: Path):
    client = DeepSeekClient.for_test(tmp_path)
    messages = [{"role": "user", "content": "x"}]

    target = client.request_cache_key(messages, role="target")
    optimizer = client.request_cache_key(messages, role="optimizer")
    executor_with_tool = client.request_cache_key(
        messages, role="executor", tools=[READ_TOOL]
    )
    executor_without_tool = client.request_cache_key(messages, role="executor")

    assert target != optimizer
    assert executor_with_tool != executor_without_tool


def test_cached_tool_call_round_trips_as_typed_data(tmp_path: Path, monkeypatch):
    client = _client_with_tool_call(tmp_path, monkeypatch)
    messages = [{"role": "user", "content": "read it"}]

    first = client.complete(messages, tools=[READ_TOOL], role="executor")
    second = client.complete(messages, tools=[READ_TOOL], role="executor")

    assert not first.cache_hit
    assert second.cache_hit
    assert second.tool_calls[0].arguments == {"path": "note.txt"}
