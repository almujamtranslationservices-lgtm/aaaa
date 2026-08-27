"""Google Gemini LLM provider (free tier available).

Uses ``POST {endpoint}/models/{model}:generateContent`` with the key sent via
the ``x-goog-api-key`` header (never in the URL, so it cannot leak into logs).
"""

from __future__ import annotations

import os

import httpx

from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.ai.llm.http_common import request_json
from ai_video_factory.core.exceptions import ProviderResponseError


class GeminiProvider(LLMProvider):
    """Google Gemini provider."""

    id = "gemini"
    DEFAULT_MODEL = "gemini-2.0-flash"
    DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("GEMINI_MODEL") or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key or "", "Content-Type": "application/json"}

    async def generate(self, request: LLMRequest) -> str:
        data = await request_json(
            "POST",
            f"{self.endpoint}/models/{self.model}:generateContent",
            provider_id=self.id,
            headers=self._headers(),
            payload={
                "systemInstruction": {"parts": [{"text": request.system}]},
                "contents": [{"role": "user", "parts": [{"text": request.user}]}],
                "generationConfig": {
                    "temperature": request.temperature,
                    "maxOutputTokens": request.max_tokens,
                },
            },
            timeout=self.timeout or 120.0,
            http_client=getattr(self, "_http_client", None),
        )
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
            raise ProviderResponseError(f"gemini: {reason}", provider=self.id)
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise ProviderResponseError(f"gemini: empty completion: {str(data)[:300]}", provider=self.id)
        return text

    async def test_connection(self) -> bool:
        await request_json(
            "GET", f"{self.endpoint}/models", provider_id=self.id,
            headers=self._headers(), timeout=self.timeout or 15.0,
            http_client=getattr(self, "_http_client", None),
        )
        return True
