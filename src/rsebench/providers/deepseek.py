"""DeepSeek V4 Flash-only provider with an immutable local response cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCKED_MODEL = "deepseek-v4-flash"
LOCKED_BASE_URL = "https://api.deepseek.com"


class CredentialsMissingError(RuntimeError):
    """Raised instead of silently substituting another model or provider."""


class DeepSeekConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = "deepseek"
    base_url: str = LOCKED_BASE_URL
    model: str = LOCKED_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.0
    max_tokens: int = Field(default=8192, gt=0)
    thinking: str = "enabled"
    timeout_seconds: float = Field(default=300, gt=0)
    max_retries: int = Field(default=4, ge=0)


class ModelResponse(BaseModel):
    content: str
    usage: dict[str, Any] = Field(default_factory=dict)
    model: str = LOCKED_MODEL
    cache_hit: bool = False
    finish_reason: str | None = None


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig, cache_dir: Path):
        if config.provider != "deepseek":
            raise ValueError("pilot provider must be deepseek")
        if config.model != LOCKED_MODEL:
            raise ValueError(f"pilot model must be exactly {LOCKED_MODEL}")
        if config.base_url.rstrip("/") != LOCKED_BASE_URL:
            raise ValueError(f"pilot base_url must be {LOCKED_BASE_URL}")
        self.config = config
        self.cache_dir = Path(cache_dir)

    @classmethod
    def from_yaml(
        cls, path: Path | str, cache_dir: Path | str | None = None
    ) -> "DeepSeekClient":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        config = DeepSeekConfig.model_validate(payload)
        load_dotenv(PROJECT_ROOT / ".env")
        output_root = Path(
            os.environ.get("RSEBENCH_OUTPUT_ROOT", PROJECT_ROOT / "outputs")
        )
        return cls(config, Path(cache_dir) if cache_dir else output_root / "cache/model")

    @classmethod
    def for_test(cls, cache_dir: Path | str) -> "DeepSeekClient":
        return cls(DeepSeekConfig(), Path(cache_dir))

    def has_credentials(self) -> bool:
        load_dotenv(PROJECT_ROOT / ".env")
        return bool(os.environ.get(self.config.api_key_env, "").strip())

    def request_cache_key(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> str:
        request = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "thinking": self.config.thinking,
            "messages": messages,
            "response_format": response_format,
        }
        encoded = json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _cache_path(self, cache_key: str) -> Path:
        safe = cache_key
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", safe):
            safe = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{safe}.json"

    def write_cache(self, cache_key: str, payload: dict[str, Any]) -> Path:
        path = self._cache_path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def _read_cache(self, cache_key: str) -> ModelResponse | None:
        path = self._cache_path(cache_key)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return ModelResponse.model_validate(payload)

    def complete(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        cache_key: str | None = None,
    ) -> ModelResponse:
        key = cache_key or self.request_cache_key(messages, response_format)
        cached = self._read_cache(key)
        if cached is not None:
            return cached

        load_dotenv(PROJECT_ROOT / ".env")
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise CredentialsMissingError(
                f"{self.config.api_key_env} is empty; no fallback model is permitted"
            )

        client = OpenAI(
            api_key=api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        if self.config.thinking == "enabled":
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception as exc:
            message = str(exc).replace(api_key, "[REDACTED]")
            raise RuntimeError(f"DeepSeek request failed: {message}") from exc

        choice = completion.choices[0]
        response = ModelResponse(
            content=choice.message.content or "",
            usage=completion.usage.model_dump() if completion.usage else {},
            model=completion.model or self.config.model,
            finish_reason=choice.finish_reason,
        )
        self.write_cache(key, response.model_dump(exclude={"cache_hit"}))
        return response
