"""Demo voice provider — real speech-like WAV tones via stdlib (DEMO MODE, §36).

Synthesises a deterministic murmur (fundamental + harmonics + vibrato +
phrase-envelope) whose duration matches the text length at the configured
speaking speed. No dependencies, no network — a genuine PCM WAV file the
whole pipeline (mixing, burning, rendering) can consume offline.
"""

from __future__ import annotations

import hashlib
import math
import struct
import wave
from pathlib import Path

from ai_video_factory.ai.voice.base import VoiceProvider
from ai_video_factory.models.audio import VoiceSettings

_SAMPLE_RATE = 22_050
_CHARS_PER_SECOND = 14.0  # rough Arabic/English narration pace


def estimate_speech_duration(text: str, *, speed: float = 1.0) -> float:
    """Duration estimate for *text* (clamped 0.8s … 30s, scaled by speed)."""
    clean = text.strip()
    if not clean:
        return 0.0
    duration = len(clean) / _CHARS_PER_SECOND
    duration = max(0.8, min(30.0, duration))
    return duration / max(0.25, speed)


class DemoVoiceProvider(VoiceProvider):
    """Offline speech-like tone generator (deterministic per text)."""

    id = "demo"

    async def synthesize(self, text: str, settings: VoiceSettings, output_path: Path) -> Path:
        text = (text or "").strip()
        if not text:
            raise ValueError("DemoVoiceProvider: empty narration text")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256(text.encode()).digest()
        base_f0 = 110.0 + (digest[0] / 255.0) * 90.0          # 110-200 Hz voice
        f0 = base_f0 * (2.0 ** (settings.pitch / 12.0))       # pitch in semitones
        duration = estimate_speech_duration(text, speed=settings.speed)
        volume = max(0.02, min(1.0, settings.volume * 0.32))  # comfortable headroom

        total_frames = int(duration * _SAMPLE_RATE)
        frames = bytearray()
        for n in range(total_frames):
            t = n / _SAMPLE_RATE
            # Phrase envelope (≈3 syllables/second) + vibrato.
            envelope = 0.55 + 0.45 * abs(math.sin(math.pi * 3.0 * t))
            vibrato = 1.0 + 0.015 * math.sin(2 * math.pi * 5.0 * t)
            frequency = f0 * vibrato
            sample = (
                math.sin(2 * math.pi * frequency * t)
                + 0.5 * math.sin(2 * math.pi * 2 * frequency * t)
                + 0.25 * math.sin(2 * math.pi * 3 * frequency * t)
            ) / 1.75
            # 300ms fade-in / 500ms fade-out.
            fade = min(1.0, t / 0.3, max(0.0, (duration - t) / 0.5))
            value = int(sample * envelope * fade * volume * 32767.0)
            frames += struct.pack("<h", max(-32768, min(32767, value)))

        with wave.open(str(output), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(_SAMPLE_RATE)
            handle.writeframes(bytes(frames))
        return output

    async def test_connection(self) -> bool:
        return True
