"""Audio domain models: voice synthesis, music, SFX and mixed assets."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class VoiceSettings(BaseModel):
    """Voice-over synthesis controls (spec §13)."""

    voice: str = "ar-SA-HamedNeural"      # sensible Arabic default (Edge TTS naming)
    language: str = "ar"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)     # 1.0 = normal
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)  # semitones
    emotion: str = "neutral"
    volume: float = Field(default=1.0, ge=0.0, le=2.0)


class MusicSettings(BaseModel):
    """Background music behaviour, including narration ducking (spec §14)."""

    track: str = ""
    enabled: bool = True
    volume: float = Field(default=0.25, ge=0.0, le=1.0)
    fade_in: float = Field(default=2.0, ge=0.0, le=30.0)   # seconds
    fade_out: float = Field(default=3.0, ge=0.0, le=30.0)  # seconds
    ducking_enabled: bool = True
    duck_level_db: float = Field(default=-14.0, ge=-40.0, le=0.0)  # music gain during narration


class AudioKind(str, Enum):
    VOICE = "voice"
    MUSIC = "music"
    SFX = "sfx"
    MIXED = "mixed"


class AudioAsset(BaseModel):
    """A concrete audio file produced by the pipeline."""

    kind: AudioKind
    path: Path
    duration_s: float = Field(default=0.0, ge=0.0)
    sample_rate: int = Field(default=44100, ge=8000)
    channels: int = Field(default=1, ge=1, le=2)
    provider: str = ""
