"""Tests: voice providers — demo WAV, edge-tts, ElevenLabs, Piper, conversion."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import wave

import httpx
import pytest

from ai_video_factory.ai.factory import create_voice_provider
from ai_video_factory.ai.voice.demo import DemoVoiceProvider, estimate_speech_duration
from ai_video_factory.media.audio_processor import (
    convert_to_wav, peak_amplitude, wav_duration, wav_info, wav_is_valid,
)
from ai_video_factory.models.audio import VoiceSettings
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")


def _tiny_wav_bytes(seconds: float = 0.2, frequency: int = 440) -> bytes:
    """A real, valid PCM WAV built with the stdlib (used as fake TTS output)."""
    rate = 16000
    frames = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        import math
        import struct

        for n in range(frames):
            value = int(0.6 * 32767 * math.sin(2 * math.pi * frequency * n / rate))
            handle.writeframes(struct.pack("<h", value))
    return buffer.getvalue()


def _tiny_mp3_bytes(tmp_path, seconds: float = 0.2) -> bytes:
    """Real MP3 bytes encoded via FFmpeg (fake cloud-TTS payloads)."""
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    mp3 = tmp_path / "_fake.mp3"
    engine.run([
        "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:a", "libmp3lame", "-b:a", "64k", str(mp3),
    ], timeout=60)
    return mp3.read_bytes()


def _engine() -> FFmpegEngine:
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    return engine


# ------------------------------------------------------------------ duration
def test_estimate_speech_duration_scales_and_clamps():
    short = estimate_speech_duration("مرحبا", speed=1.0)
    long_text = "كلمة " * 200
    assert 0.0 < short <= estimate_speech_duration(long_text.strip())
    assert estimate_speech_duration(long_text.strip()) <= 30.0
    faster = estimate_speech_duration("نص متوسط الطول هنا", speed=2.0)
    slower = estimate_speech_duration("نص متوسط الطول هنا", speed=0.5)
    assert faster < slower
    assert estimate_speech_duration("   ") == 0.0


# ----------------------------------------------------------------------- demo
def test_demo_voice_creates_valid_wav(tmp_path):
    provider = DemoVoiceProvider()
    out = tmp_path / "scene_001" / "voice.wav"
    saved = asyncio.run(provider.synthesize(
        "قصة اختفاء غامض حدث منذ مئة عام",
        VoiceSettings(voice="ar", speed=1.0, pitch=0.0, volume=1.0), out))
    assert saved == out and wav_is_valid(out)
    info = wav_info(out)
    assert info["channels"] == 1 and info["sample_width"] == 2
    expected = estimate_speech_duration("قصة اختفاء غامض حدث منذ مئة عام")
    assert info["duration_s"] == pytest.approx(expected, rel=0.05)


def test_demo_voice_deterministic_and_volume_applied(tmp_path):
    provider = DemoVoiceProvider()
    first, second, louder = (tmp_path / f"{n}.wav" for n in ("a", "b", "c"))
    text = "نفس النص تماماً هنا"
    asyncio.run(provider.synthesize(text, VoiceSettings(volume=0.4), first))
    asyncio.run(provider.synthesize(text, VoiceSettings(volume=0.4), second))
    asyncio.run(provider.synthesize(text, VoiceSettings(volume=1.0), louder))
    assert first.read_bytes() == second.read_bytes()      # deterministic per text
    assert peak_amplitude(louder) > peak_amplitude(first)  # volume honoured


def test_demo_voice_rejects_empty_text(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(DemoVoiceProvider().synthesize(
            "   ", VoiceSettings(), tmp_path / "x.wav"))


def test_demo_voice_pitch_changes_content(tmp_path):
    low, high = tmp_path / "low.wav", tmp_path / "high.wav"
    asyncio.run(DemoVoiceProvider().synthesize("نص", VoiceSettings(pitch=-6.0), low))
    asyncio.run(DemoVoiceProvider().synthesize("نص", VoiceSettings(pitch=6.0), high))
    assert low.read_bytes() != high.read_bytes()


# ------------------------------------------------------------- audio helpers
def test_convert_to_wav_produces_pcm16(tmp_path):
    engine = _engine()
    source = tmp_path / "audio.mp3"
    source.write_bytes(_tiny_mp3_bytes(tmp_path))          # real MP3 content
    out = tmp_path / "out.wav"
    convert_to_wav(source, out, engine=engine, sample_rate=22050, mono=True)
    assert wav_is_valid(out)
    assert wav_info(out)["sample_rate"] == 22050
    assert wav_info(out)["channels"] == 1
    assert wav_duration(out) == pytest.approx(0.2, abs=0.05)
    with pytest.raises(Exception):
        convert_to_wav(tmp_path / "missing.mp3", tmp_path / "y.wav", engine=engine)


def test_wav_helpers_reject_garbage(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wave file at all")
    assert wav_is_valid(bad) is False
    try:
        peak_amplitude(bad)
        raised = False
    except Exception:
        raised = True
    assert raised  # invalid PCM files cannot be measured


# ----------------------------------------------------------------------- edge
def test_edge_tts_maps_settings_and_converts(tmp_path, monkeypatch):
    engine = _engine()
    captured: dict = {}

    class FakeCommunicate:
        def __init__(self, text, voice, rate="", pitch="", volume=""):
            captured.update(text=text, voice=voice, rate=rate, pitch=pitch, volume=volume)

        async def save(self, path):
            with open(path, "wb") as handle:
                handle.write(_tiny_mp3_bytes(Path(path).parent))

    import ai_video_factory.ai.voice.edge_tts as edge_module

    monkeypatch.setattr(edge_module, "_edge_import", None, raising=False)
    provider = create_voice_provider("edge")
    provider._engine = engine
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)

    settings = VoiceSettings(voice="ar-EG-ShakirNeural", speed=1.2, pitch=3.0, volume=0.8)
    out = tmp_path / "voice.wav"
    saved = asyncio.run(provider.synthesize("مرحبا بالعالم", settings, out))

    assert saved == out and wav_is_valid(out)
    assert not out.with_suffix(".mp3").exists()          # temp cleaned up
    assert captured["voice"] == "ar-EG-ShakirNeural"
    assert captured["rate"] == "+20%"
    assert captured["pitch"] == "+3Hz"
    assert captured["volume"] == "-20%"


def test_edge_tts_empty_text(tmp_path):
    provider = create_voice_provider("edge")
    with pytest.raises(ValueError):
        asyncio.run(provider.synthesize("  ", VoiceSettings(), tmp_path / "v.wav"))


# ---------------------------------------------------------------- elevenlabs
def test_elevenlabs_request_shape_and_conversion(tmp_path):
    engine = _engine()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("xi-api-key")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=_tiny_mp3_bytes(tmp_path))

    provider = create_voice_provider("elevenlabs", api_key="xl-test")
    provider._engine = engine
    provider._http_client = _client(handler)

    settings = VoiceSettings(voice="rachel", emotion="dramatic")
    out = tmp_path / "v.wav"
    saved = asyncio.run(provider.synthesize("Hello world", settings, out))

    assert saved == out and wav_is_valid(out)
    assert "/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM" in captured["url"]  # preset resolved
    assert "output_format=mp3_44100_128" in captured["url"]
    assert captured["key"] == "xl-test"
    assert captured["payload"]["model_id"] == "eleven_multilingual_v2"
    assert captured["payload"]["voice_settings"]["style"] == 0.4        # emotion honoured


def test_elevenlabs_error_mapping(tmp_path):
    provider = create_voice_provider("elevenlabs", api_key="xl-test")
    provider._http_client = _client(lambda r: httpx.Response(401, text="invalid key"))
    with pytest.raises(Exception, match="401"):
        asyncio.run(provider.synthesize("text", VoiceSettings(), tmp_path / "v.wav"))


# --------------------------------------------------------------------- piper
def test_piper_saves_wav_directly(tmp_path):
    wav_bytes = _tiny_wav_bytes()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        if str(request.url).endswith("/api/voices"):
            return httpx.Response(200, json=[{"id": "ar-fac-low"}])
        return httpx.Response(200, content=wav_bytes)

    provider = create_voice_provider("piper")
    provider.endpoint = "http://testserver"
    provider._http_client = _client(handler)

    out = tmp_path / "v.wav"
    saved = asyncio.run(provider.synthesize("تجربة", VoiceSettings(voice="ar-fac-low"), out))
    assert saved.read_bytes() == wav_bytes
    assert captured["params"]["text"] == "تجربة"
    assert captured["params"]["voice"] == "ar-fac-low"
    assert asyncio.run(provider.test_connection()) is True
