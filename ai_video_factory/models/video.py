"""Video domain models: motion parameters, subtitles, rendering, timeline."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class MotionParams(BaseModel):
    """Image-to-video generation controls (spec §12)."""

    motion_strength: float = Field(default=6.0, ge=0.0, le=10.0)
    camera_motion: str = "static"          # e.g. zoom_in / pan_left / orbit
    duration_s: float = Field(default=4.0, ge=1.0, le=20.0)
    fps: int = Field(default=30, ge=12, le=60)
    seed: int | None = None


class SubtitlePosition(str, Enum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


class SubtitleSettings(BaseModel):
    """Subtitle look & feel (spec §15) — used by SRT/ASS writers and burning."""

    enabled: bool = True
    format: str = "srt"                     # srt | ass
    burn: bool = True                       # burn into the video (vs. embed/soft)
    font_family: str = "Cairo"              # good Arabic + Latin coverage
    font_size: int = Field(default=42, ge=12, le=200)
    position: SubtitlePosition = SubtitlePosition.BOTTOM
    color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = Field(default=3, ge=0, le=20)
    background: str = "semi-transparent black box"  # style hint for the ASS/ffmpeg filter
    animation: str = "fade"                 # fade | pop | slide | none


class RenderSettings(BaseModel):
    """Final video encoding controls (FFmpeg, spec §17)."""

    encoder: str = "libx264"
    quality_crf: int = Field(default=20, ge=0, le=51)
    preset: str = "medium"                  # ultrafast … veryslow
    pixel_format: str = "yuv420p"
    audio_bitrate: str = "192k"
    audio_sample_rate: int = 44100


class TimelineItem(BaseModel):
    """One entry of the assembled timeline before rendering."""

    scene_id: int
    start_s: float = Field(ge=0.0)
    duration_s: float = Field(gt=0.0)
    video_path: Path | None = None
    image_path: Path | None = None          # fallback when no video clip exists
    audio_paths: list[Path] = Field(default_factory=list)
    transition_in: str = "cut"


class VideoAsset(BaseModel):
    """A concrete video file produced by the pipeline."""

    path: Path
    duration_s: float = Field(default=0.0, ge=0.0)
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)
    fps: float = Field(default=0.0, ge=0.0)
    provider: str = ""
