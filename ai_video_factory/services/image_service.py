"""Image generation service — scene prompts ➜ per-scene image files (spec §11, §21).

For every scene: build an :class:`ImageRequest` from the scene's stored image
prompt (and negative prompt persisted in ``prompt.json``), run the selected
provider, save ``scenes/scene_XXX/image.png``, register the asset in the DB
(sha256 + size) and advance the scene status to ``image_ready``.

Cache rule (spec §21): existing non-empty images are skipped unless
``force=True``. A failing scene is isolated: it is marked ``failed`` and the
run continues, so one provider hiccup never destroys the whole batch.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_factory.ai.factory import create_image_provider
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.project import Project
from ai_video_factory.models.prompt import DEFAULT_NEGATIVE_PROMPT
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.services.scene_service import load_scene_prompt
from ai_video_factory.utils.file_utils import sha256_file

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int], None]  # (done, total, scene_id)


@dataclass
class ImageGenResult:
    """Summary of one image-generation run."""

    generated: list[Path] = field(default_factory=list)
    skipped_cached: int = 0
    failed_scenes: list[int] = field(default_factory=list)
    provider_id: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed_scenes


def _negative_for(project_dir: Path, scene: Scene) -> str:
    payload = load_scene_prompt(project_dir, scene.scene_id)
    if payload and payload.get("negative_prompt"):
        return str(payload["negative_prompt"])
    return DEFAULT_NEGATIVE_PROMPT


def generate_scene_images(
    project: Project,
    manager: ProjectManager,
    *,
    provider_id: str = "demo",
    model: str | None = None,
    force: bool = False,
    asset_repo=None,
    on_progress: ProgressCallback | None = None,
) -> ImageGenResult:
    """Generate (or reuse cached) images for every scene of *project*.

    Args:
        project: project (mutated in place; auto-saved at the end).
        manager: ProjectManager for canonical asset paths.
        provider_id: image provider to use (``demo`` works offline).
        model: optional provider model override (checkpoint / engine / model id).
        force: regenerate even when an image already exists.
        asset_repo: optional AssetRepository — registers sha256 + size per image.
        on_progress: optional callback invoked after each scene.
    """
    from ai_video_factory.ai.image.base import ImageRequest

    result = ImageGenResult(provider_id=provider_id)
    if not project.scenes:
        return result

    provider = create_image_provider(provider_id, model=model)
    project_dir = manager.project_dir(project)
    total = len(project.scenes)

    for index, scene in enumerate(project.scenes, start=1):
        image_path = manager.asset_path(project, scene.scene_id, "image")
        if not force and image_path.exists() and image_path.stat().st_size > 0:
            scene.assets["image"] = _relative(project_dir, image_path)
            if scene.status not in (SceneStatus.IMAGE_READY, SceneStatus.VIDEO_READY,
                                    SceneStatus.AUDIO_READY, SceneStatus.DONE):
                scene.status = SceneStatus.IMAGE_READY
            result.skipped_cached += 1
            if on_progress:
                on_progress(index, total, scene.scene_id)
            continue

        seed = scene.seed if scene.seed is not None else 42 + scene.scene_id
        try:
            request = ImageRequest(
                prompt=scene.image_prompt or scene.visual_description or scene.title,
                negative_prompt=_negative_for(project_dir, scene),
                width=project.width,
                height=project.height,
                seed=seed,
                output_path=image_path,
                scene_ref=f"scene_{scene.scene_id:03d}",
            )
            saved = asyncio.run(provider.generate(request))
            scene.assets["image"] = _relative(project_dir, Path(saved))
            scene.status = SceneStatus.IMAGE_READY
            result.generated.append(Path(saved))
            if asset_repo is not None:
                try:
                    asset_repo.register(
                        project.id, scene.scene_id, "image", Path(saved),
                        sha256=sha256_file(saved), size_bytes=saved.stat().st_size,
                    )
                except Exception:  # noqa: BLE001 — registry is auxiliary, never fatal
                    logger.warning("Scene %03d: asset registry write skipped (DB error)",
                                   scene.scene_id, exc_info=True)
            logger.info("Scene %03d image ready (%s, %d KB)",
                        scene.scene_id, provider_id, saved.stat().st_size // 1024)
        except Exception as exc:  # noqa: BLE001 — isolate scene failures
            scene.status = SceneStatus.FAILED
            result.failed_scenes.append(scene.scene_id)
            logger.exception("Scene %d image generation failed (%s): %s",
                             scene.scene_id, provider_id, exc)
        finally:
            if on_progress:
                on_progress(index, total, scene.scene_id)

    try:
        manager.save(project, autosave=True)
    except Exception:  # noqa: BLE001
        logger.exception("Auto-saving project '%s' after image generation failed", project.name)
    return result


def _relative(project_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project_dir)).replace("\\", "/")
    except ValueError:
        return str(path)
