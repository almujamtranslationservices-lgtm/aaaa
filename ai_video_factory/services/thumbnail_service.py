"""Smart-thumbnail service — branded thumbnail from the project's real assets.

Chooses the best real background available (a frame of the rendered
``final.mp4`` → the first scene image → deterministic gradient), derives
title/subtitle/duration-chip defaults from the project (SEO title wins), and
caches the result + the exact recipe in ``output/thumbnail.json`` so edits and
re-runs are reproducible.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.media.thumbnail_generator import (
    format_duration, generate_thumbnail,
)
from ai_video_factory.models.project import Project

logger = logging.getLogger(__name__)


@dataclass
class ThumbnailResult:
    path: Path | None = None
    cached: bool = False
    meta: dict | None = None
    background_source: str = "gradient"      # final-frame | scene-image | gradient
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.path is not None and self.error is None


def _timeline_total(project: Project) -> float:
    return sum(max(scene.duration, 0.0) for scene in project.scenes)


def _default_meta(project: Project) -> dict:
    title = (project.seo.title if project.seo and project.seo.title else project.name).strip()
    subtitle = (project.idea or "").strip()
    if not subtitle and project.scenes:
        subtitle = (project.scenes[0].narration or "").strip()
    return {
        "title": title[:100] or "فيديو",
        "subtitle": " ".join(subtitle.split())[:90],
        "badge": format_duration(_timeline_total(project)) if project.scenes else "",
        "frame_time_s": min(1.0, (_timeline_total(project) or 2.0) / 2),
    }


def _background(project: Project, manager: ProjectManager, out_dir: Path,
                frame_time_s: float) -> tuple[Path | None, str]:
    """Best real background: final-video frame → first scene image → None."""
    final = out_dir / "final.mp4"
    if final.exists():
        try:
            from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

            engine = FFmpegEngine()
            seek_s = max(0.0, frame_time_s)
            try:                              # never seek past the last frame
                duration = float(engine.probe(final)["format"]["duration"])
                # short clips have few frames — the middle is always safe
                seek_s = min(seek_s, max(0.0, duration / 2), max(0.0, duration - 0.1))
            except Exception:  # noqa: BLE001 — probing is best-effort
                pass
            frame = out_dir / "_thumb_frame.png"
            engine.extract_thumbnail(final, frame, time_s=seek_s)
            if frame.exists() and frame.stat().st_size > 0:
                return frame, "final-frame"
        except Exception:  # noqa: BLE001 — frame extraction is best-effort
            logger.warning("Frame extraction failed — trying scene images")
    for scene in sorted(project.scenes, key=lambda s: s.scene_id):
        image = manager.asset_path(project, scene.scene_id, "image")
        if image.exists():
            return image, "scene-image"
    return None, "gradient"


def generate_smart_thumbnail(
    project: Project,
    manager: ProjectManager,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    badge: str | None = None,
    frame_time_s: float | None = None,
    force: bool = False,
) -> ThumbnailResult:
    """Render ``output/thumbnail.png`` (cached against its recipe)."""
    out_dir = manager.project_dir(project) / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "thumbnail.png"
    meta_path = out_dir / "thumbnail.json"

    meta = _default_meta(project)
    for key, value in (("title", title), ("subtitle", subtitle), ("badge", badge)):
        if value is not None:
            meta[key] = value.strip()
    if frame_time_s is not None:
        meta["frame_time_s"] = max(0.0, float(frame_time_s))

    if not force and png_path.exists() and meta_path.exists():
        try:
            if json.loads(meta_path.read_text(encoding="utf-8")) == meta:
                return ThumbnailResult(path=png_path, cached=True, meta=meta,
                                       background_source="cached")
        except Exception:  # noqa: BLE001 — corrupt cache → regenerate
            logger.warning("Corrupt thumbnail.json — regenerating")

    background, source = _background(project, manager, out_dir, meta["frame_time_s"])
    try:
        generate_thumbnail(
            png_path,
            title=meta["title"], subtitle=meta["subtitle"], badge=meta["badge"],
            background=background,
        )
    except Exception as exc:  # noqa: BLE001 — isolate thumbnail failures
        logger.exception("Smart thumbnail generation failed")
        return ThumbnailResult(error=f"{type(exc).__name__}: {exc}")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    logger.info("Smart thumbnail → %s (background: %s)", png_path, source)
    return ThumbnailResult(path=png_path, meta=meta, background_source=source)


def load_thumbnail_meta(project: Project, manager: ProjectManager) -> dict | None:
    meta_path = manager.project_dir(project) / "output" / "thumbnail.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
