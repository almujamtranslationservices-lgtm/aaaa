"""Video generation service — scene images ➜ per-scene clips (spec §12, §21).

For every scene with a generated image: build a :class:`VideoRequest` (motion
from the scene's video prompt / camera hints, seed from the scene), run the
selected image-to-video provider, save ``scenes/scene_XXX/video.mp4``,
register the asset (sha256 + size), advance the scene to ``video_ready``.

Cache rule (spec §21): existing clips are skipped unless ``force=True``.
Scenes without an image are skipped with an explicit reason (the video pipeline
needs the still first). Failures are isolated per scene.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_factory.ai.factory import create_video_provider
from ai_video_factory.ai.video.demo import pick_motion
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.project import Project
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.models.video import MotionParams
from ai_video_factory.utils.file_utils import sha256_file

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int], None]  # (done, total, scene_id)


@dataclass
class VideoGenResult:
    """Summary of one video-generation run."""

    generated: list[Path] = field(default_factory=list)
    skipped_cached: int = 0
    skipped_no_image: list[int] = field(default_factory=list)
    failed_scenes: list[int] = field(default_factory=list)
    provider_id: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed_scenes


def _motion_for(project: Project, scene: Scene) -> MotionParams:
    """Motion parameters: duration/fps from the project, camera from hints."""
    hint = f"{scene.video_prompt} {scene.camera}"
    camera_motion = pick_motion(scene.scene_id - 1, hint)
    # Map Ken Burns words back to MotionParams vocabulary where they overlap.
    return MotionParams(
        motion_strength=6.0,
        camera_motion=camera_motion,
        duration_s=min(max(scene.duration, 1.0), 20.0),
        fps=project.fps,
        seed=scene.seed,
    )


def generate_scene_videos(
    project: Project,
    manager: ProjectManager,
    *,
    provider_id: str = "demo",
    model: str | None = None,
    force: bool = False,
    asset_repo=None,
    on_progress: ProgressCallback | None = None,
) -> VideoGenResult:
    """Generate (or reuse cached) clips for every scene of *project*."""
    from ai_video_factory.ai.video.base import VideoRequest

    result = VideoGenResult(provider_id=provider_id)
    if not project.scenes:
        return result

    provider = create_video_provider(provider_id, model=model)
    project_dir = manager.project_dir(project)
    total = len(project.scenes)

    for index, scene in enumerate(project.scenes, start=1):
        video_path = manager.asset_path(project, scene.scene_id, "video")
        image_path = manager.asset_path(project, scene.scene_id, "image")

        if not image_path.exists():
            result.skipped_no_image.append(scene.scene_id)
            logger.info("Scene %03d: no image yet — skipping video (run images first)",
                        scene.scene_id)
            if on_progress:
                on_progress(index, total, scene.scene_id)
            continue

        if not force and video_path.exists() and video_path.stat().st_size > 0:
            scene.assets["video"] = _relative(project_dir, video_path)
            if scene.status not in (SceneStatus.VIDEO_READY, SceneStatus.AUDIO_READY, SceneStatus.DONE):
                scene.status = SceneStatus.VIDEO_READY
            result.skipped_cached += 1
            if on_progress:
                on_progress(index, total, scene.scene_id)
            continue

        try:
            request = VideoRequest(
                image_path=image_path,
                prompt=scene.video_prompt or scene.visual_description,
                motion=_motion_for(project, scene),
                width=project.width,
                height=project.height,
                output_path=video_path,
                scene_ref=f"scene_{scene.scene_id:03d}",
            )
            saved = asyncio.run(provider.generate(request))
            scene.assets["video"] = _relative(project_dir, Path(saved))
            scene.status = SceneStatus.VIDEO_READY
            result.generated.append(Path(saved))
            if asset_repo is not None:
                try:
                    asset_repo.register(
                        project.id, scene.scene_id, "video", Path(saved),
                        sha256=sha256_file(saved), size_bytes=saved.stat().st_size,
                    )
                except Exception:  # noqa: BLE001 — registry is auxiliary, never fatal
                    logger.warning("Scene %03d: video asset registry skipped (DB error)",
                                   scene.scene_id, exc_info=True)
            logger.info("Scene %03d video ready (%s, %d KB)",
                        scene.scene_id, provider_id, saved.stat().st_size // 1024)
        except Exception as exc:  # noqa: BLE001 — isolate scene failures
            scene.status = SceneStatus.FAILED
            result.failed_scenes.append(scene.scene_id)
            logger.exception("Scene %d video generation failed (%s): %s",
                             scene.scene_id, provider_id, exc)
        finally:
            if on_progress:
                on_progress(index, total, scene.scene_id)

    try:
        manager.save(project, autosave=True)
    except Exception:  # noqa: BLE001
        logger.exception("Auto-saving project '%s' after video generation failed", project.name)
    return result


def _relative(project_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project_dir)).replace("\\", "/")
    except ValueError:
        return str(path)
