from pathlib import Path
from types import SimpleNamespace

import pytest

import rsebench.providers.deepseek as deepseek
from rsebench.providers.deepseek import (
    CredentialsMissingError,
    DeepSeekClient,
    DeepSeekConfig,
)


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
