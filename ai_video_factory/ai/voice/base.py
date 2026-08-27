"""Voice provider interface — implemented by every TTS backend (spec §13)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from ai_video_factory.models.audio import VoiceSettings


class VoiceProvider(ABC):
    """Base class for all text-to-speech providers."""

    id: str = "voice"

    def __init__(self, *, model: str | None = None, api_key: str | None = None,
                 endpoint: str | None = None, timeout: float | None = None,
                 http_client: httpx.AsyncClient | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        #: Injectable HTTP client (tests pass one backed by MockTransport).
        self._http_client = http_client

    @abstractmethod
    async def synthesize(self, text: str, settings: VoiceSettings, output_path: Path) -> Path:
        """Synthesise *text* to an audio file at *output_path* and return it."""

    async def test_connection(self) -> bool:
        """Cheap availability probe for the provider settings page."""
        return True
