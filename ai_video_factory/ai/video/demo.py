"""Demo video provider — REAL Ken Burns clips via FFmpeg (DEMO MODE, spec §36).

Animates each scene's generated still (zoom / pan) entirely offline through
``FFmpegEngine.image_to_video`` — genuine MP4 files, exact project dimensions,
so the pipeline produces actual videos without any AI service or API key.
"""

from __future__ import annotations

from pathlib import Path

from ai_video_factory.ai.video.base import VideoProvider, VideoRequest
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine


def pick_motion(scene_index: int, hint: str = "") -> str:
    """Choose a Ken Burns motion: explicit hint wins, else rotate by scene."""
    hint = (hint or "").lower()
    if "zoom out" in hint or "pull back" in hint or "zoom-out" in hint:
        return "zoom_out"
    if "pan left" in hint:
        return "pan_left"
    if "pan right" in hint:
        return "pan_right"
    if "static" in hint or "locked" in hint:
        return "static"
    return ("zoom_in", "pan_right", "zoom_out", "pan_left")[scene_index % 4]


class DemoVideoProvider(VideoProvider):
    """Offline Ken Burns clip generator (FFmpeg zoompan)."""

    id = "demo"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._engine = FFmpegEngine()

    async def generate(self, request: VideoRequest) -> Path:
        if request.output_path is None:
            raise ValueError("DemoVideoProvider requires request.output_path")
        if not request.image_path.exists():
            raise FileNotFoundError(
                f"DemoVideoProvider: source image missing: {request.image_path}")
        motion_params = request.motion
        motion_hint = ""
        scene_index = 0
        if request.scene_ref and request.scene_ref.startswith("scene_"):
            try:
                scene_index = int(request.scene_ref.split("_")[1]) - 1
            except (IndexError, ValueError):
                scene_index = 0
        if motion_params is not None:
            motion_hint = motion_params.camera_motion or ""
            duration = motion_params.duration_s
            fps = motion_params.fps
        else:
            duration, fps = 4.0, 30

        motion = pick_motion(scene_index, motion_hint)
        return self._engine.image_to_video(
            request.image_path,
            request.output_path,
            duration=duration,
            fps=fps,
            width=request.width,
            height=request.height,
            motion=motion,
        )

    async def test_connection(self) -> bool:
        return self._engine.available
