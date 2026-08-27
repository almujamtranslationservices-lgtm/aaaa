"""ElevenLabs voice provider — real API (spec §13, ``ELEVENLABS_API_KEY``).

``POST /v1/text-to-speech/{voice_id}?output_format=mp3_44100_128`` with the
``xi-api-key`` header; MP3 bytes are converted to canonical WAV via FFmpeg.

VoiceSettings mapping: ``voice`` holds the ElevenLabs *voice id* (or a known
public name), emotion maps to style exaggeration via ``voice_settings``.
"""

from __future__ import annotations

import os
from pathlib import Path

from ai_video_factory.ai.http_common import request_bytes
from ai_video_factory.ai.voice.base import VoiceProvider
from ai_video_factory.media.audio_processor import convert_to_wav
from ai_video_factory.models.audio import VoiceSettings
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

#: Stable public voice ids (Rachel / Adam / Bella) — users can override freely.
VOICE_PRESETS = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "adam": "pNInz6obpgDQGcFmaJgB",
    "bella": "EXAVITQu4vr4xnSDxMaL",
}


class ElevenLabsProvider(VoiceProvider):
    """ElevenLabs TTS (paid cloud)."""

    id = "elevenlabs"
    DEFAULT_MODEL = "eleven_multilingual_v2"
    DEFAULT_ENDPOINT = "https://api.elevenlabs.io"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("ELEVENLABS_MODEL") or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")
        self._engine = FFmpegEngine()

    def _resolve_voice_id(self, name: str) -> str:
        return VOICE_PRESETS.get((name or "").strip().lower(), (name or "").strip() or VOICE_PRESETS["rachel"])

    async def synthesize(self, text: str, settings: VoiceSettings, output_path: Path) -> Path:
        text = (text or "").strip()
        if not text:
            raise ValueError("elevenlabs: empty narration text")
        if not self._engine.available:
            raise RuntimeError("elevenlabs: FFmpeg required for MP3→WAV conversion")
        if not self.api_key:
            raise RuntimeError("elevenlabs: ELEVENLABS_API_KEY not configured")

        voice_id = self._resolve_voice_id(settings.voice)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_mp3 = output.with_suffix(".mp3")

        # Emotion → stability mapping (energetic emotions = less stable voice).
        stability = 0.45 if settings.emotion not in ("", "neutral") else 0.6
        content = await request_bytes(
            "POST",
            f"{self.endpoint}/v1/text-to-speech/{voice_id}",
            provider_id=self.id,
            headers={"xi-api-key": self.api_key, "Accept": "audio/mpeg"},
            params={"output_format": "mp3_44100_128"},
            payload={
                "text": text,
                "model_id": self.model,
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": 0.75,
                    "style": 0.4 if settings.emotion not in ("", "neutral") else 0.0,
                    "use_speaker_boost": True,
                },
            },
            timeout=self.timeout or 180.0,
            http_client=self._http_client,
        )
        temp_mp3.write_bytes(content)
        try:
            return convert_to_wav(temp_mp3, output, engine=self._engine, mono=True)
        finally:
            temp_mp3.unlink(missing_ok=True)

    async def test_connection(self) -> bool:
        from ai_video_factory.ai.http_common import request_json

        await request_json(
            "GET", f"{self.endpoint}/v1/user", provider_id=self.id,
            headers={"xi-api-key": self.api_key},
            timeout=self.timeout or 15.0, http_client=self._http_client,
        )
        return True
