"""Subtitle service — per-scene and project-level subtitle files (spec §15).

Writes ``scenes/scene_XXX/subtitle.srt`` (relative timings, useful per clip)
plus a combined ``subtitles.srt``/``subtitles.ass`` at the project root with
absolute timings for the assembled timeline and full SubtitleSettings styling.
Everything is cached and scenes without narration are skipped explicitly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.media.subtitle_processor import (
    build_project_cues, build_scene_cues, cues_to_ass, cues_to_srt,
)
from ai_video_factory.models.project import Project
from ai_video_factory.models.scene import Scene, SceneStatus

logger = logging.getLogger(__name__)


@dataclass
class SubtitleResult:
    """Summary of one subtitle generation run."""

    scene_files: list[Path] = field(default_factory=list)
    project_files: list[Path] = field(default_factory=list)
    cached: int = 0
    skipped_no_narration: list[int] = field(default_factory=list)
    cue_count: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.project_files)


def generate_subtitles(
    project: Project,
    manager: ProjectManager,
    *,
    force: bool = False,
) -> SubtitleResult:
    """Generate per-scene SRTs + the combined project subtitle files."""
    result = SubtitleResult()
    settings = project.settings.subtitles
    project_dir = manager.project_dir(project)

    for scene in project.scenes:
        if not (scene.narration or "").strip():
            result.skipped_no_narration.append(scene.scene_id)
            continue
        scene_dir = project_dir / "scenes" / f"scene_{scene.scene_id:03d}"
        srt_path = scene_dir / "subtitle.srt"
        if force or not srt_path.exists():
            cues = build_scene_cues(scene, voice_path=scene_dir / "voice.wav")
            scene_dir.mkdir(parents=True, exist_ok=True)
            srt_path.write_text(cues_to_srt(cues), encoding="utf-8")
            result.scene_files.append(srt_path)
        else:
            result.cached += 1
        scene.assets["subtitle"] = f"scenes/scene_{scene.scene_id:03d}/subtitle.srt"

    if result.scene_files or result.cached:
        scene_dir_of = lambda scene: project_dir / "scenes" / f"scene_{scene.scene_id:03d}"  # noqa: E731
        cues = build_project_cues(project, scene_dir_of=scene_dir_of)
        result.cue_count = len(cues)
        if cues:
            srt_file = project_dir / "subtitles.srt"
            srt_file.write_text(cues_to_srt(cues), encoding="utf-8")
            result.project_files.append(srt_file)
            if settings.format == "ass":
                ass_file = project_dir / "subtitles.ass"
                ass_file.write_text(
                    cues_to_ass(cues, settings, width=1280, height=720),
                    encoding="utf-8",
                )
                result.project_files.append(ass_file)

    logger.info(
        "Subtitles: %d scene files, %d cues, %d skipped (no narration)",
        len(result.scene_files), result.cue_count, len(result.skipped_no_narration),
    )
    try:
        manager.save(project, autosave=True)
    except Exception:  # noqa: BLE001
        logger.exception("Auto-saving project '%s' after subtitles failed", project.name)
    return result


def scene_has_subtitles(scene: Scene) -> bool:
    """A scene is subtitle-ready when narration exists (cues derivable)."""
    return bool((scene.narration or "").strip())


def status_after_subtitles(scene: Scene) -> SceneStatus:
    """Subtitles never downgrade an assembled/rendered scene."""
    if scene.status == SceneStatus.DONE:
        return SceneStatus.DONE
    return SceneStatus.AUDIO_READY
