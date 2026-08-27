"""LLM provider interface.

Every provider — cloud or local — implements :meth:`LLMProvider.generate`.
JSON generation is centralised in :meth:`LLMProvider.generate_json`, which
applies the automatic extraction/repair cascade from
``utils.validation.parse_llm_json`` (spec §7).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from ai_video_factory.utils.validation import parse_llm_json


@dataclass
class LLMRequest:
    """One completion request."""

    system: str
    user: str
    max_tokens: int = 4096
    temperature: float = 0.7


class LLMProvider(ABC):
    """Base class for all language-model providers."""

    id: str = "llm"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        #: Injectable HTTP client (tests pass one backed by MockTransport).
        self._http_client = http_client

    @abstractmethod
    async def generate(self, request: LLMRequest) -> str:
        """Return the model's raw text reply for *request*."""

    async def generate_json(self, request: LLMRequest) -> dict[str, Any]:
        """Generate and parse structured JSON (with auto-repair)."""
        text = await self.generate(request)
        return parse_llm_json(text)

    def describe(self) -> str:
        """Human-readable identity for logs / the provider status page."""
        parts = [f"{type(self).__name__}(id={self.id}"]
        if self.model:
            parts.append(f"model={self.model}")
        if self.endpoint:
            parts.append(f"endpoint={self.endpoint}")
        parts.append("key=***" if self.api_key else "key=none")
        return ", ".join(parts) + ")"
