from types import SimpleNamespace

import pytest

from rsebench.adapters import skills_coach


def test_anthropic_shape_is_backed_by_locked_deepseek(monkeypatch):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content="ok")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(skills_coach, "OpenAI", lambda **kwargs: fake)

    client = skills_coach.DeepSeekAnthropicCompat(api_key="fixture-key")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=32,
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.content[0].text == "ok"
    assert calls[0]["model"] == "deepseek-v4-flash"
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_adapter_rejects_missing_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        skills_coach.DeepSeekAnthropicCompat()
