"""Audio processing — WAV utilities and format conversion (PHASE 9+).

Everything real, everything through :class:`FFmpegEngine` (no scattered
subprocess calls). The audio *mixing* system (ducking, fades, multi-track)
arrives in PHASE 10 on top of these primitives.
"""

from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path

from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

logger = logging.getLogger(__name__)


def convert_to_wav(
    source: Path | str,
    output: Path | str,
    *,
    engine: FFmpegEngine | None = None,
    sample_rate: int | None = None,
    mono: bool = False,
) -> Path:
    """Convert any audio file (mp3/ogg/…) to PCM16 WAV via FFmpeg.

    Args:
        sample_rate: optional resample target (e.g. 44100); None keeps native.
        mono: downmix to a single channel.
    """
    engine = engine or FFmpegEngine()
    source, output = Path(source), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    args = ["-y", "-i", str(source)]
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    if mono:
        args += ["-ac", "1"]
    args += ["-c:a", "pcm_s16le", str(output)]
    engine.run(args, timeout=max(60.0, 300.0))
    if not output.exists() or output.stat().st_size < 44:
        raise ValueError(f"convert_to_wav: no WAV produced at {output}")
    return output


def wav_info(path: Path | str) -> dict:
    """Read WAV metadata with the stdlib ``wave`` module (no FFmpeg needed).

    Returns keys: duration_s, sample_rate, channels, sample_width, frames.
    """
    path = Path(path)
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate() or 1
        return {
            "duration_s": frames / float(rate),
            "sample_rate": rate,
            "channels": handle.getnchannels(),
            "sample_width": handle.getsampwidth(),
            "frames": frames,
        }


def wav_duration(path: Path | str) -> float:
    """Duration of a WAV file in seconds."""
    return wav_info(path)["duration_s"]


def wav_is_valid(path: Path | str) -> bool:
    """True when the file is a readable, non-empty PCM WAV."""
    try:
        info = wav_info(path)
    except (wave.Error, OSError):
        return False
    return info["frames"] > 0 and info["sample_rate"] > 0


def peak_amplitude(path: Path | str) -> float:
    """Normalised peak amplitude (0.0-1.0) of a 16-bit WAV — used by tests
    to assert volume handling."""
    path = Path(path)
    with wave.open(str(path), "rb") as handle:
        assert handle.getsampwidth() == 2, "peak_amplitude expects 16-bit PCM"
        frames = handle.readframes(handle.getnframes())
    count = len(frames) // 2
    if count == 0:
        return 0.0
    samples = struct.unpack(f"<{count}h", frames[: count * 2])
    return max(abs(sample) for sample in samples) / 32768.0


def segment_peak(path: Path | str, start_s: float, end_s: float) -> float:
    """Peak amplitude inside a time window of a 16-bit WAV (ducking tests)."""
    path = Path(path)
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        handle.setpos(min(int(start_s * rate), handle.getnframes()))
        frames = handle.readframes(max(0, int((end_s - start_s) * rate)))
    count = len(frames) // 2
    if count == 0:
        return 0.0
    samples = struct.unpack(f"<{count}h", frames[: count * 2])
    return max(abs(sample) for sample in samples) / 32768.0


# --------------------------------------------------------------- generators
def generate_ambient_music(
    output: Path | str,
    *,
    duration_s: float,
    seed: int = 0,
    volume: float = 0.5,
    sample_rate: int = 22_050,
) -> Path:
    """Procedural ambient pad (offline DEMO MODE background music).

    Slowly-evolving chord (root + fifth + octave + minor third) with
    independent slow LFOs per voice — deterministic per *seed*.
    """
    import hashlib
    import random

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed or 1)
    digest = hashlib.sha256(str(seed).encode()).digest()
    root = 110.0 * (2.0 ** ((digest[0] % 12) / 12.0))          # any of 12 roots
    chord = (root, root * 1.5, root * 2.0, root * 2.997)       # airy voicing
    lfo_rates = [0.05 + 0.07 * rng.random() for _ in chord]
    lfo_phases = [rng.random() * 6.28 for _ in chord]

    total_frames = max(1, int(duration_s * sample_rate))
    frames = bytearray()
    for n in range(total_frames):
        t = n / sample_rate
        sample = 0.0
        for voice_freq, rate_hz, phase in zip(chord, lfo_rates, lfo_phases):
            shimmer = 0.6 + 0.4 * math.sin(2 * math.pi * rate_hz * t + phase)
            sample += math.sin(2 * math.pi * voice_freq * t) * shimmer
        sample /= len(chord) * 1.6
        fade = min(1.0, t / 1.5, max(0.0, (duration_s - t) / 2.0))
        value = int(sample * fade * volume * 32767.0)
        frames += struct.pack("<h", max(-32768, min(32767, value)))

    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))
    return output


_SFX_ARCHETYPES = ("wind", "tone", "rumble", "shimmer")


def generate_sfx(
    output: Path | str,
    *,
    description: str,
    seed: int | None = None,
    duration_s: float | None = None,
    volume: float = 0.5,
    sample_rate: int = 22_050,
) -> Path:
    """Procedural sound effect chosen from the scene's SFX description.

    The description hash picks an archetype (wind / tone / rumble / shimmer)
    and its parameters — deterministic, offline, always a valid WAV.
    """
    import hashlib
    import random

    description = (description or "").strip()
    if not description:
        raise ValueError("generate_sfx: empty description")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(description.lower().encode()).digest()
    rng = random.Random(int.from_bytes(digest[:4], "big"))
    archetype = _SFX_ARCHETYPES[digest[4] % len(_SFX_ARCHETYPES)]
    duration_s = duration_s or 1.5 + (digest[5] % 15) / 10.0     # 1.5 - 3.0s

    total_frames = max(1, int(duration_s * sample_rate))
    frames = bytearray()
    noise_state = 0.0
    for n in range(total_frames):
        t = n / sample_rate
        envelope = min(1.0, t / 0.15, max(0.0, (duration_s - t) / 0.4))
        if archetype == "wind":
            white = rng.uniform(-1, 1)
            noise_state = 0.98 * noise_state + 0.02 * white      # low-pass noise
            sample = noise_state * 2.2
        elif archetype == "tone":
            frequency = 520.0 + (digest[6] % 600)
            decay = max(0.05, 1.0 - t / duration_s)
            sample = math.sin(2 * math.pi * frequency * t) * decay
        elif archetype == "rumble":
            white = rng.uniform(-1, 1)
            noise_state = 0.995 * noise_state + 0.005 * white    # deep rumble
            sample = noise_state * 3.0
        else:  # shimmer
            frequency = 1200.0 + (digest[6] % 900)
            tremolo = 0.5 + 0.5 * math.sin(2 * math.pi * 9.0 * t)
            sample = math.sin(2 * math.pi * frequency * t) * tremolo * 0.5
        value = int(sample * envelope * volume * 32767.0)
        frames += struct.pack("<h", max(-32768, min(32767, value)))

    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))
    return output
