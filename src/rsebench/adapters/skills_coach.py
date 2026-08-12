"""Skills-Coach compatibility client backed only by DeepSeek."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"


@dataclass
class TextBlock:
    text: str


@dataclass
class CompatResponse:
    content: list[TextBlock]


class _Messages:
    def __init__(self, owner: "DeepSeekAnthropicCompat") -> None:
        self.owner = owner

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None = None,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> CompatResponse:
        del model, kwargs
        normalized = list(messages)
        if system:
            normalized.insert(0, {"role": "system", "content": system})
        text = self.owner.complete_text(
            normalized,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return CompatResponse(content=[TextBlock(text=text)])


class DeepSeekAnthropicCompat:
    """Expose ``messages.create`` while hard-locking provider and model."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        **_: Any,
    ) -> None:
        key = (api_key or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is empty")
        if base_url and base_url.rstrip("/") != BASE_URL:
            raise ValueError(f"Skills-Coach adapter requires {BASE_URL}")
        self._client = OpenAI(api_key=key, base_url=BASE_URL, timeout=timeout)
        self.messages = _Messages(self)

    def complete_text(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0,
            "max_tokens": min(max_tokens, 4096),
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        response = self._client.chat.completions.create(**kwargs)
        if not response.choices:
            raise RuntimeError("DeepSeek returned no choices")
        return response.choices[0].message.content or ""

    def complete_json(
        self, prompt: str, *, max_tokens: int = 1024
    ) -> dict[str, Any]:
        text = self.complete_text(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("DeepSeek JSON response must be an object")
        return payload
