"""Microsoft Edge TTS provider — free, no API key (spec §13, §26).

Wraps the ``edge-tts`` package (async). Streams MP3 audio, then converts to
the canonical PCM WAV through :class:`FFmpegEngine` so every downstream stage
(mixing, burning) sees one uniform format.

VoiceSettings mapping:
    voice   → edge voice name (e.g. ``ar-SA-HamedNeural``, ``en-US-GuyNeural``)
    speed   → rate ``+/-N%`` (0.5x → -50%, 1.5x → +50%)
    pitch   → ``+/-N Hz``
    volume  → ``+/-N%``
"""

from __future__ import annotations

import logging
from pathlib import Path

from ai_video_factory.ai.voice.base import VoiceProvider
from ai_video_factory.media.audio_processor import convert_to_wav
from ai_video_factory.models.audio import VoiceSettings
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "ar-SA-HamedNeural"


def _signed_percent(value: float, scale: float = 100.0) -> str:
    return f"{int(round(value * scale)):+d}%"


class EdgeTTSProvider(VoiceProvider):
    """Edge TTS (free cloud, no key)."""

    id = "edge"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._engine = FFmpegEngine()

    async def synthesize(self, text: str, settings: VoiceSettings, output_path: Path) -> Path:
        text = (text or "").strip()
        if not text:
            raise ValueError("edge: empty narration text")
        if not self._engine.available:
            raise RuntimeError(
                "edge: FFmpeg is required to convert Edge MP3 to WAV — install it "
                "or run: pip install imageio-ffmpeg"
            )
        import edge_tts

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_mp3 = output.with_suffix(".mp3")
        communicate = edge_tts.Communicate(
            text,
            settings.voice or DEFAULT_VOICE,
            rate=_signed_percent(settings.speed - 1.0),
            pitch=f"{int(round(settings.pitch)):+d}Hz",
            volume=_signed_percent(settings.volume - 1.0),
        )
        await communicate.save(str(temp_mp3))
        try:
            wav_path = convert_to_wav(temp_mp3, output, engine=self._engine, mono=True)
        finally:
            temp_mp3.unlink(missing_ok=True)
        logger.debug("edge: synthesised %.1fs → %s", wav_path.stat().st_size / 44100, output)
        return wav_path

    async def test_connection(self) -> bool:
        import edge_tts

        voices = await edge_tts.list_voices()
        if not voices:
            raise RuntimeError("edge: voice list came back empty")
        return True
