"""Rendering service — assemble every asset into the FINAL video (spec §16-17).

Pipeline per project (all stages progress-reported and cache-aware):

1. **Ensure clips** — every scene needs a video.mp4; scenes with only an image
   get a Ken Burns clip (``image_to_video``) at the project's frame size.
2. **Concat** — clips are normalised and concatenated (``concat_videos``).
3. **Audio track** — per-scene ``mix.wav`` files are padded/trimmed to each
   scene's duration and concatenated (``concat_audio``); scenes without any
   audio contribute real silence.
4. **Mux** — video + audio (``mux_audio``, AAC per RenderSettings).
5. **Burn subtitles** — when enabled; SRT gets a force_style built from
   SubtitleSettings, ASS files burn with their own embedded styling.
6. **Thumbnail** — one decoded frame (``extract_thumbnail``).

Result: ``<project>/output/final.mp4`` + ``output/thumbnail.png``; project
status → COMPLETED and scenes → DONE.
"""

from __future__ import annotations

import logging
import struct
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.project import Project, ProjectStatus
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.models.video import SubtitleSettings, TimelineItem
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine, FFmpegError

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]

_MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right")


@dataclass
class RenderResult:
    """Summary of one final-render run."""

    final_path: Path | None = None
    thumbnail_path: Path | None = None
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    burned_subtitles: bool = False
    image_fallback_scenes: list[int] = field(default_factory=list)
    silent_scenes: list[int] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    cached: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.final_path is not None


def assemble_timeline(project: Project, manager: ProjectManager) -> list[TimelineItem]:
    """Build timeline items from scene assets (video, else image fallback)."""
    project_dir = manager.project_dir(project)
    items: list[TimelineItem] = []
    cursor = 0.0
    for scene in project.scenes:
        scene_dir = project_dir / "scenes" / f"scene_{scene.scene_id:03d}"
        video = scene_dir / "video.mp4"
        image = scene_dir / "image.png"
        if not video.exists() and not image.exists():
            raise FFmpegError(
                f"Scene {scene.scene_id}: neither video.mp4 nor image.png exists"
            )
        items.append(TimelineItem(
            scene_id=scene.scene_id,
            start_s=cursor,
            duration_s=max(scene.duration, 0.5),
            video_path=video if video.exists() else None,
            image_path=image if not video.exists() and image.exists() else None,
            audio_paths=[scene_dir / "mix.wav"] if (scene_dir / "mix.wav").exists() else [],
        ))
        cursor += max(scene.duration, 0.5)
    return items


def _write_silence(path: Path, duration_s: float, sample_rate: int = 44100) -> Path:
    """Real silent stereo WAV (used for scenes with no audio at all)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(duration_s * sample_rate))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00\x00\x00" * frames)
    return path


def _srt_force_style(settings: SubtitleSettings) -> dict[str, str]:
    """Map SubtitleSettings → libavfilter force_style fields (SRT path)."""
    from ai_video_factory.media.subtitle_processor import ass_color

    return {
        "FontName": settings.font_family,
        "FontSize": settings.font_size,
        "PrimaryColour": ass_color(settings.color),
        "OutlineColour": ass_color(settings.stroke_color),
        "OutlineWidth": max(1, settings.stroke_width),
        "Bold": "0",
    }


def render_final_video(
    project: Project,
    manager: ProjectManager,
    *,
    engine: FFmpegEngine | None = None,
    on_progress: ProgressCallback | None = None,
    force: bool = False,
) -> RenderResult:
    """Render ``output/final.mp4`` from the project's current assets."""
    engine = engine or FFmpegEngine()
    result = RenderResult()
    report = on_progress or (lambda fraction, message: None)

    def step(fraction: float, message: str) -> None:
        result.stages.append(message)
        report(fraction, message)

    if not project.scenes:
        result.error = "no scenes to render"
        return result
    if not engine.available:
        result.error = "ffmpeg not available"
        return result

    project_dir = manager.project_dir(project)
    out_dir = project_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / "final.mp4"

    if final_path.exists() and not force:
        result.cached = True
        result.final_path = final_path
        result.thumbnail_path = out_dir / "thumbnail.png"
        result.stages.append("cache hit")
        try:
            info = engine.probe(final_path)
            result.duration_s = float(info["format"]["duration"])
        except FFmpegError:
            pass
        step(1.0, "final video already rendered")
        return result

    project.status = ProjectStatus.RENDERING
    try:
        # ---------------------------------------------------------- 1. clips
        timeline = assemble_timeline(project, manager)
        clips: list[Path] = []
        for index, item in enumerate(timeline):
            scene = project.scenes[index]
            if item.video_path is not None:
                clips.append(item.video_path)
                continue
            clip_path = out_dir / f"scene_{item.scene_id:03d}_clip.mp4"
            if not (clip_path.exists() and clip_path.stat().st_size > 0):
                engine.image_to_video(
                    item.image_path, clip_path,
                    duration=item.duration_s, fps=project.fps,
                    width=project.width, height=project.height,
                    motion=_MOTIONS[item.scene_id % len(_MOTIONS)],
                )
            clips.append(clip_path)
            result.image_fallback_scenes.append(item.scene_id)
        step(0.15, f"{len(clips)} clips ready")

        # ---------------------------------------------------------- 2. video
        video_only = out_dir / "video_only.mp4"
        engine.concat_videos(clips, video_only, width=project.width,
                             height=project.height, fps=project.fps,
                             crf=project.settings.render.quality_crf)
        step(0.45, "clips concatenated")

        # ---------------------------------------------------------- 3. audio
        audio_clips: list[Path] = []
        durations: list[float] = []
        for index, item in enumerate(timeline):
            durations.append(item.duration_s)
            if item.audio_paths:
                audio_clips.append(item.audio_paths[0])
            else:
                scene = project.scenes[index]
                voice = manager.asset_path(project, scene.scene_id, "voice")
                if voice.exists():
                    audio_clips.append(voice)
                else:
                    audio_clips.append(_write_silence(
                        out_dir / f"scene_{item.scene_id:03d}_silence.wav", item.duration_s))
                    result.silent_scenes.append(item.scene_id)
        full_mix = out_dir / "full_mix.wav"
        engine.concat_audio(audio_clips, full_mix, durations_s=durations,
                            sample_rate=project.settings.render.audio_sample_rate)
        step(0.6, "audio track assembled")

        # ------------------------------------------------------------ 4. mux
        rendered = out_dir / "rendered.mp4"
        engine.mux_audio(video_only, full_mix, rendered,
                         audio_bitrate=project.settings.render.audio_bitrate,
                         sample_rate=project.settings.render.audio_sample_rate)
        step(0.75, "audio muxed")

        # -------------------------------------------------------- 5. subtitles
        subtitle_settings = project.settings.subtitles
        source = rendered
        if subtitle_settings.enabled and subtitle_settings.burn:
            srt = project_dir / "subtitles.srt"
            ass = project_dir / "subtitles.ass"
            subtitle_file = ass if (subtitle_settings.format == "ass" and ass.exists()) else (
                srt if srt.exists() else None)
            if subtitle_file is not None:
                style = None if subtitle_file.suffix == ".ass" else _srt_force_style(subtitle_settings)
                engine.burn_subtitles(source, subtitle_file, final_path, style=style)
                result.burned_subtitles = True
                source = final_path
                step(0.9, f"subtitles burned ({subtitle_file.name})")
            else:
                step(0.9, "subtitles missing — skipped burn")
        if source is not final_path:
            final_path.write_bytes(source.read_bytes())
        result.final_path = final_path

        # -------------------------------------------------------- 6. thumbnail
        info = engine.probe(final_path)
        result.duration_s = float(info["format"]["duration"])
        video_stream = next(s for s in info["streams"] if s.get("codec_type") == "video")
        result.width, result.height = int(video_stream["width"]), int(video_stream["height"])
        result.thumbnail_path = engine.extract_thumbnail(
            final_path, out_dir / "thumbnail.png",
            time_s=min(1.0, result.duration_s / 2))
        step(1.0, "thumbnail extracted")

        # -------------------------------------------------------- 7. statuses
        for scene in project.scenes:
            if scene.status != SceneStatus.FAILED:
                scene.status = SceneStatus.DONE
        project.status = ProjectStatus.COMPLETED
        for path in (video_only, rendered):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove intermediate %s", path)
        manager.save(project, autosave=True)
        logger.info("Final video rendered: %s (%.2fs)", final_path, result.duration_s)
        return result
    except Exception as exc:  # noqa: BLE001 — render boundary
        result.error = f"{type(exc).__name__}: {exc}"
        project.status = ProjectStatus.FAILED
        try:
            manager.save(project, autosave=True)
        except Exception:  # noqa: BLE001
            logger.exception("Saving failed project state failed")
        logger.exception("Final render failed")
        return result
