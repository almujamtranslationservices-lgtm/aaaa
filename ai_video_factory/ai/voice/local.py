"""Piper local TTS provider — fully offline (spec §13, §25).

Targets a Piper HTTP server (e.g. ``piper-http-server`` or the Wyoming-
compatible REST wrapper) configured via ``LOCAL_TTS_BASE_URL``::

    POST {endpoint}/api/tts?text=…&voice=…   →  audio/wav bytes
    GET  {endpoint}/api/voices               →  available voice ids

WAV bytes are stored directly — no conversion, no FFmpeg dependency.
"""

from __future__ import annotations

from pathlib import Path

from ai_video_factory.ai.http_common import request_bytes, request_json
from ai_video_factory.ai.voice.base import VoiceProvider
from ai_video_factory.models.audio import VoiceSettings


class PiperLocalProvider(VoiceProvider):
    """Piper local TTS (offline)."""

    id = "piper"
    DEFAULT_MODEL = "ar-fac-low"   # any installed Piper voice model
    DEFAULT_ENDPOINT = "http://localhost:5000"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    async def synthesize(self, text: str, settings: VoiceSettings, output_path: Path) -> Path:
        text = (text or "").strip()
        if not text:
            raise ValueError("piper: empty narration text")
        voice = settings.voice or self.model
        content = await request_bytes(
            "POST", f"{self.endpoint}/api/tts", provider_id=self.id,
            params={"text": text, "voice": voice},
            timeout=self.timeout or 120.0,
            http_client=self._http_client,
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return output

    async def test_connection(self) -> bool:
        await request_json(
            "GET", f"{self.endpoint}/api/voices", provider_id=self.id,
            timeout=self.timeout or 10.0, http_client=self._http_client,
        )
        return True
