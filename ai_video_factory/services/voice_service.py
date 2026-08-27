"""Voice generation service — scene narration ➜ per-scene voice.wav (spec §13, §21).

For every scene: synthesise its narration with the project's VoiceSettings
(voice / speed / pitch / volume), save ``scenes/scene_XXX/voice.wav``, register
the asset, advance the scene to ``audio_ready``.

Cache rule (spec §21): existing voice files are skipped unless ``force=True``.
Scenes without narration are skipped explicitly (not failures). A scene whose
narration text changed can be regenerated with ``force`` — the change detection
is left to the caller (editors autosave the scene before rerunning).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_factory.ai.factory import create_voice_provider
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.project import Project
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.utils.file_utils import sha256_file

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int], None]  # (done, total, scene_id)


@dataclass
class VoiceGenResult:
    """Summary of one voice-generation run."""

    generated: list[Path] = field(default_factory=list)
    skipped_cached: int = 0
    skipped_no_narration: list[int] = field(default_factory=list)
    failed_scenes: list[int] = field(default_factory=list)
    provider_id: str = ""
    total_duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed_scenes


def generate_scene_voices(
    project: Project,
    manager: ProjectManager,
    *,
    provider_id: str = "demo",
    model: str | None = None,
    force: bool = False,
    asset_repo=None,
    on_progress: ProgressCallback | None = None,
) -> VoiceGenResult:
    """Generate (or reuse cached) narration audio for every scene of *project*."""
    result = VoiceGenResult(provider_id=provider_id)
    if not project.scenes:
        return result

    provider = create_voice_provider(provider_id, model=model)
    settings = project.settings.voice
    project_dir = manager.project_dir(project)
    total = len(project.scenes)

    for index, scene in enumerate(project.scenes, start=1):
        voice_path = manager.asset_path(project, scene.scene_id, "voice")

        if not (scene.narration or "").strip():
            result.skipped_no_narration.append(scene.scene_id)
            logger.info("Scene %03d: no narration — skipping voice", scene.scene_id)
            if on_progress:
                on_progress(index, total, scene.scene_id)
            continue

        if not force and voice_path.exists() and voice_path.stat().st_size > 44:
            scene.assets["voice"] = _relative(project_dir, voice_path)
            _advance_status(scene)
            result.skipped_cached += 1
            if on_progress:
                on_progress(index, total, scene.scene_id)
            continue

        try:
            saved = asyncio.run(provider.synthesize(scene.narration, settings, voice_path))
            scene.assets["voice"] = _relative(project_dir, Path(saved))
            _advance_status(scene)
            result.generated.append(Path(saved))
            if asset_repo is not None:
                try:
                    asset_repo.register(
                        project.id, scene.scene_id, "voice", Path(saved),
                        sha256=sha256_file(saved), size_bytes=saved.stat().st_size,
                    )
                except Exception:  # noqa: BLE001 — registry is auxiliary, never fatal
                    logger.warning("Scene %03d: voice asset registry skipped (DB error)",
                                   scene.scene_id, exc_info=True)
            logger.info("Scene %03d voice ready (%s, %d KB)",
                        scene.scene_id, provider_id, Path(saved).stat().st_size // 1024)
        except Exception as exc:  # noqa: BLE001 — isolate scene failures
            scene.status = SceneStatus.FAILED
            result.failed_scenes.append(scene.scene_id)
            logger.exception("Scene %d voice generation failed (%s): %s",
                             scene.scene_id, provider_id, exc)
        finally:
            if on_progress:
                on_progress(index, total, scene.scene_id)

    try:
        manager.save(project, autosave=True)
    except Exception:  # noqa: BLE001
        logger.exception("Auto-saving project '%s' after voice generation failed", project.name)
    return result


def _advance_status(scene: Scene) -> None:
    """Voice only advances scenes that have not reached a later stage."""
    if scene.status not in (SceneStatus.AUDIO_READY, SceneStatus.DONE):
        scene.status = SceneStatus.AUDIO_READY


def _relative(project_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project_dir)).replace("\\", "/")
    except ValueError:
        return str(path)
