"""Project model: metadata, video parameters and nested generation settings."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

from ai_video_factory.models.audio import MusicSettings, VoiceSettings
from ai_video_factory.models.character import Character
from ai_video_factory.models.seo import SEOPackage
from ai_video_factory.models.scene import Scene
from ai_video_factory.models.video import RenderSettings, SubtitleSettings


class VideoType(str, Enum):
    YOUTUBE_SHORT = "youtube_short"
    YOUTUBE_VIDEO = "youtube_video"
    TIKTOK = "tiktok"
    INSTAGRAM_REEL = "instagram_reel"
    DOCUMENTARY = "documentary"
    CINEMATIC_STORY = "cinematic_story"
    CUSTOM = "custom"


class AspectRatio(str, Enum):
    R_16_9 = "16:9"
    R_9_16 = "9:16"
    R_1_1 = "1:1"


class ResolutionPreset(str, Enum):
    P480 = "480p"
    P720 = "720p"
    P1080 = "1080p"
    P4K = "4k"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    SCRIPT_READY = "script_ready"
    ASSETS_IN_PROGRESS = "assets_in_progress"
    READY_TO_RENDER = "ready_to_render"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


#: (aspect_ratio, fps) defaults per video type.
VIDEO_TYPE_DEFAULTS: dict[VideoType, tuple[AspectRatio, int]] = {
    VideoType.YOUTUBE_SHORT: (AspectRatio.R_9_16, 30),
    VideoType.YOUTUBE_VIDEO: (AspectRatio.R_16_9, 30),
    VideoType.TIKTOK: (AspectRatio.R_9_16, 30),
    VideoType.INSTAGRAM_REEL: (AspectRatio.R_9_16, 30),
    VideoType.DOCUMENTARY: (AspectRatio.R_16_9, 24),
    VideoType.CINEMATIC_STORY: (AspectRatio.R_16_9, 24),
    VideoType.CUSTOM: (AspectRatio.R_16_9, 30),
}

_RESOLUTION_HEIGHTS: dict[ResolutionPreset, int] = {
    ResolutionPreset.P480: 480,
    ResolutionPreset.P720: 720,
    ResolutionPreset.P1080: 1080,
    ResolutionPreset.P4K: 2160,
}


def _even(value: int) -> int:
    return value - (value % 2)


def resolution_dims(resolution: ResolutionPreset, aspect: AspectRatio) -> tuple[int, int]:
    """Pixel dimensions for a (resolution, aspect) pair — always even numbers.

    The preset names the *short* side of the frame (industry convention:
    a 1080p portrait video is 1080×1920, a 4K landscape video 3840×2160).

    >>> resolution_dims(ResolutionPreset.P1080, AspectRatio.R_16_9)
    (1920, 1080)
    >>> resolution_dims(ResolutionPreset.P1080, AspectRatio.R_9_16)
    (1080, 1920)
    """
    short_side = _RESOLUTION_HEIGHTS[resolution]
    if aspect == AspectRatio.R_16_9:
        return _even(round(short_side * 16 / 9)), _even(short_side)
    if aspect == AspectRatio.R_9_16:
        return _even(short_side), _even(round(short_side * 16 / 9))
    return _even(short_side), _even(short_side)  # 1:1


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectSettings(BaseModel):
    """Per-project generation settings."""

    language: str = "ar"
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    music: MusicSettings = Field(default_factory=MusicSettings)
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)


class Project(BaseModel):
    """A complete video project (source of truth serialised to project.json)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    schema_version: int = 1
    name: str = Field(min_length=1, max_length=120)
    idea: str = ""
    video_type: VideoType = VideoType.YOUTUBE_VIDEO
    aspect_ratio: AspectRatio = AspectRatio.R_16_9
    resolution: ResolutionPreset = ResolutionPreset.P1080
    fps: int = Field(default=30, ge=12, le=120)
    target_duration: float = Field(default=60.0, gt=0, le=3600.0)
    status: ProjectStatus = ProjectStatus.DRAFT

    characters: list[Character] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    seo: SEOPackage | None = None

    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)

    #: Runtime-only location of project.json (excluded from serialisation).
    file_path: Path | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def width(self) -> int:
        return resolution_dims(self.resolution, self.aspect_ratio)[0]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def height(self) -> int:
        return resolution_dims(self.resolution, self.aspect_ratio)[1]

    @property
    def total_duration(self) -> float:
        """Sum of scene durations (0 before scene generation)."""
        return round(sum(scene.duration for scene in self.scenes), 2)

    def scene_by_id(self, scene_id: int) -> Scene | None:
        return next((scene for scene in self.scenes if scene.scene_id == scene_id), None)

    def character(self, name: str) -> Character | None:
        return next((char for char in self.characters if char.name == name), None)
