from pathlib import Path
from types import SimpleNamespace

import pytest

import rsebench.providers.deepseek as deepseek
from rsebench.providers.deepseek import (
    CredentialsMissingError,
    DeepSeekClient,
    DeepSeekConfig,
)
from rsebench.usage import aggregate_token_usage


def _set_ledger_context(monkeypatch, ledger: Path) -> None:
    values = {
        "RSEBENCH_TOKEN_LEDGER_DIR": str(ledger),
        "RSEBENCH_TOKEN_RUN_ID": "run-1",
        "RSEBENCH_TOKEN_DOMAIN": "math",
        "RSEBENCH_TOKEN_BENCHMARK": "dapo_fixed_1000",
        "RSEBENCH_TOKEN_ARM": "generation",
        "RSEBENCH_TOKEN_STAGE": "noise_generator",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_client_rejects_non_flash_model(tmp_path: Path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(
        "provider: deepseek\n"
        "base_url: https://api.deepseek.com\n"
        "model: gpt-5.5\n"
        "api_key_env: DEEPSEEK_API_KEY\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="deepseek-v4-flash"):
        DeepSeekClient.from_yaml(cfg)


def test_cached_response_does_not_require_credentials(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = DeepSeekClient.for_test(cache_dir=tmp_path)
    client.write_cache("fixture", {"content": "ok", "usage": {}, "model": "deepseek-v4-flash"})
    response = client.complete(
        [{"role": "user", "content": "x"}], cache_key="fixture"
    )
    assert response.content == "ok"
    assert response.cache_hit


def test_uncached_response_never_falls_back_without_credentials(tmp_path: Path, monkeypatch):
    isolated_project = tmp_path / "isolated-project"
    isolated_project.mkdir()
    monkeypatch.setattr(deepseek, "PROJECT_ROOT", isolated_project)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("RSEBENCH_DATA_ROOT", raising=False)
    client = DeepSeekClient.for_test(cache_dir=tmp_path)
    with pytest.raises(CredentialsMissingError, match="DEEPSEEK_API_KEY"):
        client.complete([{"role": "user", "content": "x"}], cache_key="missing")


def test_cache_key_does_not_embed_prompt_text(tmp_path: Path):
    client = DeepSeekClient.for_test(cache_dir=tmp_path)
    key = client.request_cache_key([{"role": "user", "content": "sensitive prompt"}])
    assert len(key) == 64
    assert "sensitive" not in key


def test_disabled_thinking_is_sent_explicitly(tmp_path: Path, monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"ok":true}'),
                        finish_reason="stop",
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
    client = DeepSeekClient(
        DeepSeekConfig(thinking="disabled"), cache_dir=tmp_path
    )

    client.complete(
        [{"role": "user", "content": "return json"}], cache_key="disabled"
    )

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_worktree_env_falls_back_to_shared_project_credentials(tmp_path: Path, monkeypatch):
    worktree = tmp_path / "main" / ".worktrees" / "feature"
    shared = tmp_path / "main"
    worktree.mkdir(parents=True)
    (worktree / ".env").write_text(
        f"DEEPSEEK_API_KEY=\nRSEBENCH_DATA_ROOT={shared / 'data'}\n",
        encoding="utf-8",
    )
    (shared / ".env").write_text("DEEPSEEK_API_KEY=fake-shared-key\n", encoding="utf-8")
    monkeypatch.setattr(deepseek, "PROJECT_ROOT", worktree)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("RSEBENCH_DATA_ROOT", raising=False)

    deepseek.load_project_environment()

    assert deepseek.os.environ["DEEPSEEK_API_KEY"] == "fake-shared-key"


def test_provider_and_cache_calls_separate_billed_and_logical_usage(
    tmp_path: Path, monkeypatch
):
    ledger = tmp_path / "token_usage"
    _set_ledger_context(monkeypatch, ledger)

    class FakeUsage:
        def model_dump(self):
            return {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="OK", tool_calls=[]),
                        finish_reason="stop",
                    )
                ],
                usage=FakeUsage(),
                model="deepseek-v4-flash",
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(deepseek, "OpenAI", FakeOpenAI)
    client = DeepSeekClient(
        DeepSeekConfig(thinking="disabled"), cache_dir=tmp_path / "cache"
    )

    first = client.complete(
        [{"role": "user", "content": "return OK"}], cache_key="same"
    )
    second = client.complete(
        [{"role": "user", "content": "return OK"}], cache_key="same"
    )
    summary = aggregate_token_usage(ledger)

    assert not first.cache_hit
    assert second.cache_hit
    assert summary["attempted_calls"] == 2
    assert summary["successful_calls"] == 2
    assert summary["observed_coverage"] == 1.0
    assert summary["cache_hit_calls"] == 1
    assert summary["billed_tokens"]["total_tokens"] == 15
    assert summary["logical_tokens"]["total_tokens"] == 30
    assert summary["groups"]["stage"]["noise_generator"]["attempted_calls"] == 2


def test_terminal_provider_error_records_only_safe_unobservable_metadata(
    tmp_path: Path, monkeypatch
):
    ledger = tmp_path / "token_usage"
    _set_ledger_context(monkeypatch, ledger)

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("provider detail contains test-secret")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FailingCompletions())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setattr(deepseek, "OpenAI", FakeOpenAI)
    client = DeepSeekClient(
        DeepSeekConfig(thinking="disabled", max_retries=0),
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(RuntimeError, match=r"\[REDACTED\]"):
        client.complete([{"role": "user", "content": "x"}], cache_key="failure")

    summary = aggregate_token_usage(ledger)
    event_text = "".join(
        path.read_text(encoding="utf-8")
        for path in (ledger / "events").glob("*.jsonl")
    )
    assert summary["attempted_calls"] == 1
    assert summary["failed_calls"] == 1
    assert summary["unobservable_calls"] == 1
    assert summary["billed_tokens"]["total_tokens"] == 0
    assert "RuntimeError" in event_text
    assert "test-secret" not in event_text
    assert "provider detail" not in event_text
