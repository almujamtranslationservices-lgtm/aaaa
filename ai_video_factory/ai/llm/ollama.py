"""Ollama local LLM provider — fully local, no API key, no cost (spec §25).

Talks to the Ollama HTTP API (default ``http://localhost:11434``)::

    POST /api/chat   {"model", "messages", "stream": false, "options"}

The model defaults to ``OLLAMA_MODEL`` (env) or ``llama3.1``.
"""

from __future__ import annotations

import os

import httpx

from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.ai.llm.http_common import request_json
from ai_video_factory.core.exceptions import ProviderResponseError


class OllamaProvider(LLMProvider):
    """Ollama chat provider (local)."""

    id = "ollama"
    DEFAULT_MODEL = "llama3.1"
    DEFAULT_ENDPOINT = "http://localhost:11434"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("OLLAMA_MODEL") or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    async def generate(self, request: LLMRequest) -> str:
        data = await request_json(
            "POST",
            f"{self.endpoint}/api/chat",
            provider_id=self.id,
            payload={
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.user},
                ],
                "options": {
                    "temperature": request.temperature,
                    "num_predict": request.max_tokens,
                },
            },
            timeout=self.timeout or 300.0,
            http_client=getattr(self, "_http_client", None),
        )
        # Ollama may return HTTP 200 with {"error": "..."} on model failures.
        if "error" in data:
            raise ProviderResponseError(f"ollama: {data['error']}", provider=self.id)
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError(f"ollama: empty completion: {str(data)[:300]}", provider=self.id)
        return content

    async def test_connection(self) -> bool:
        """Cheap probe: ``GET /api/tags`` lists installed models."""
        data = await request_json(
            "GET", f"{self.endpoint}/api/tags", provider_id=self.id,
            timeout=self.timeout or 15.0, http_client=getattr(self, "_http_client", None),
        )
        models = [model.get("name", "") for model in data.get("models", [])]
        if self.model not in models and f"{self.model}:latest" not in models:
            raise ProviderResponseError(
                f"ollama: server reachable but model '{self.model}' is not installed "
                f"(run: ollama pull {self.model})",
                provider=self.id,
            )
        return True
