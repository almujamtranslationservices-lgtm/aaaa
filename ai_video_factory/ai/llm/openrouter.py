"""OpenRouter LLM provider — OpenAI-compatible API aggregating many models.

Free models exist (e.g. ``meta-llama/llama-3.1-8b-instruct:free``); the model
defaults to ``OPENROUTER_MODEL`` (env).
"""

from __future__ import annotations

import os

from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.ai.llm.http_common import parse_openai_choice, request_json


class OpenRouterProvider(LLMProvider):
    """OpenRouter chat provider."""

    id = "openrouter"
    DEFAULT_MODEL = "meta-llama/llama-3.1-8b-instruct:free"
    DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("OPENROUTER_MODEL") or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ai-video-factory",
            "X-Title": "AI Video Factory",
        }

    async def generate(self, request: LLMRequest) -> str:
        data = await request_json(
            "POST",
            f"{self.endpoint}/chat/completions",
            provider_id=self.id,
            headers=self._headers(),
            payload={
                "model": self.model,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.user},
                ],
            },
            timeout=self.timeout or 120.0,
            http_client=getattr(self, "_http_client", None),
        )
        return parse_openai_choice(data, provider_id=self.id)

    async def test_connection(self) -> bool:
        from ai_video_factory.ai.llm.http_common import request_json as _rq

        await _rq(
            "GET", f"{self.endpoint}/models", provider_id=self.id,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout or 15.0,
            http_client=getattr(self, "_http_client", None),
        )
        return True
