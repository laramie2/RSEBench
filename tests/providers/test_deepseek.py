from pathlib import Path

import pytest

from rsebench.providers.deepseek import CredentialsMissingError, DeepSeekClient


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
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = DeepSeekClient.for_test(cache_dir=tmp_path)
    with pytest.raises(CredentialsMissingError, match="DEEPSEEK_API_KEY"):
        client.complete([{"role": "user", "content": "x"}], cache_key="missing")


def test_cache_key_does_not_embed_prompt_text(tmp_path: Path):
    client = DeepSeekClient.for_test(cache_dir=tmp_path)
    key = client.request_cache_key([{"role": "user", "content": "sensitive prompt"}])
    assert len(key) == 64
    assert "sensitive" not in key
