"""OpenAI LLM provider (ChatCompletions, OpenAI-compatible)."""

from __future__ import annotations

import os

from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.ai.llm.http_common import parse_openai_choice, request_json


class OpenAIProvider(LLMProvider):
    """OpenAI chat provider."""

    id = "openai"
    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_ENDPOINT = "https://api.openai.com/v1"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("OPENAI_MODEL") or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

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
        await request_json(
            "GET", f"{self.endpoint}/models", provider_id=self.id,
            headers=self._headers(), timeout=self.timeout or 15.0,
            http_client=getattr(self, "_http_client", None),
        )
        return True
