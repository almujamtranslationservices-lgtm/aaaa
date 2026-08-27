"""Audio system service — music + SFX + per-scene mixing (spec §14, §21).

Pipeline per project:

1. ``ensure_music_track`` — project-level ``music.wav``: either the track the
   user placed in ``assets/music`` (``project.settings.music.track``) or a
   procedural ambient bed (offline DEMO MODE), cached.
2. ``generate_scene_sfx`` — ``scenes/scene_XXX/sfx.wav`` from the scene's SFX
   description (procedural; swap-in of real SFX libraries is a provider away).
3. ``generate_scene_mixes`` — for every scene: voice + music (looped, faded,
   **auto-ducked during narration** via sidechain compression) + SFX →
   ``scenes/scene_XXX/mix.wav``, using the project's MusicSettings.

All stages are cached (existing files skipped unless ``force=True``) and
failures are isolated per scene.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.media.audio_processor import generate_ambient_music, generate_sfx, wav_duration, wav_is_valid
from ai_video_factory.models.project import Project
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.utils.file_utils import sha256_file

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int], None]  # (done, total, scene_id)

#: duck_level_db (e.g. -14) → sidechain compression ratio (deeper duck = higher).
def duck_ratio_for(duck_level_db: float) -> float:
    return max(2.0, min(20.0, 2.0 + abs(duck_level_db) / 3.0))


@dataclass
class AudioMixResult:
    """Summary of one full audio-mix run."""

    mixes: list[Path] = field(default_factory=list)
    cached: int = 0
    sfx_generated: list[Path] = field(default_factory=list)
    music_track: Path | None = None
    music_generated: bool = False
    failed_scenes: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_scenes


def ensure_music_track(
    project: Project,
    manager: ProjectManager,
    *,
    force: bool = False,
) -> tuple[Path, bool]:
    """Return (music_path, generated?) — cached unless *force*.

    Priority: a user track from ``assets/music`` named in
    ``project.settings.music.track`` → procedural ambient bed.
    """
    music_path = manager.project_dir(project) / "music.wav"
    if music_path.exists() and not force:
        return music_path, False

    track_name = (project.settings.music.track or "").strip()
    if track_name:
        from ai_video_factory.config.settings import project_root

        candidate = project_root() / "assets" / "music" / track_name
        if candidate.exists():
            music_path.parent.mkdir(parents=True, exist_ok=True)
            music_path.write_bytes(candidate.read_bytes())
            return music_path, False
        logger.warning("Music track '%s' not found in assets/music — using ambient bed",
                       track_name)

    generate_ambient_music(
        music_path,
        duration_s=max(10.0, project.total_duration or project.target_duration),
        seed=abs(hash(project.id)) % (2**31),
        volume=0.9,   # bed at full level; mix stage applies MusicSettings.volume
    )
    logger.info("Ambient music bed generated → %s", music_path)
    return music_path, True


def generate_scene_sfx(
    project: Project,
    manager: ProjectManager,
    *,
    force: bool = False,
) -> list[Path]:
    """Per-scene procedural SFX (cached; scenes without SFX text are skipped)."""
    generated: list[Path] = []
    for scene in project.scenes:
        if not (scene.sfx or "").strip():
            continue
        sfx_path = manager.asset_path(project, scene.scene_id, "sfx")
        if sfx_path.exists() and not force:
            scene.assets["sfx"] = _relative(manager, sfx_path, project)
            continue
        try:
            generate_sfx(sfx_path, description=scene.sfx)
            scene.assets["sfx"] = _relative(manager, sfx_path, project)
            generated.append(sfx_path)
        except Exception:  # noqa: BLE001 — SFX must never block the mix
            logger.exception("Scene %d: SFX generation failed", scene.scene_id)
    return generated


def mix_scene_audio(
    project: Project,
    scene: Scene,
    *,
    music_path: Path | None,
    output: Path,
    engine=None,
) -> Path:
    """Mix ONE scene: voice + ducked music + sfx → *output* (mix.wav)."""
    manager_engine = engine or __import__(
        "ai_video_factory.utils.ffmpeg_utils", fromlist=["FFmpegEngine"]
    ).FFmpegEngine()

    project_dir = output.parent.parent
    voice_path = output.parent / "voice.wav"
    voice = voice_path if voice_path.exists() and wav_is_valid(voice_path) else None

    sfx_paths: list[Path] = []
    sfx_path = output.parent / "sfx.wav"
    if sfx_path.exists() and wav_is_valid(sfx_path):
        sfx_paths.append(sfx_path)

    music_settings = project.settings.music
    music = music_path if (music_settings.enabled and music_path and music_path.exists()) else None
    if not (voice or music or sfx_paths):
        raise ValueError(f"Scene {scene.scene_id}: no audio sources to mix")

    return manager_engine.mix_audio(
        output,
        voice=voice,
        music=music,
        sfx=sfx_paths,
        duration_s=(max(scene.duration, wav_duration(voice)) if voice is not None
                    else scene.duration),
        music_volume=music_settings.volume,
        music_fade_in=min(music_settings.fade_in, max(0.0, scene.duration / 3)),
        music_fade_out=min(music_settings.fade_out, max(0.0, scene.duration / 3)),
        ducking_enabled=music_settings.ducking_enabled,
        duck_ratio=duck_ratio_for(music_settings.duck_level_db),
    )


def generate_scene_mixes(
    project: Project,
    manager: ProjectManager,
    *,
    force: bool = False,
    asset_repo=None,
    on_progress: ProgressCallback | None = None,
) -> AudioMixResult:
    """Full audio pass: music bed + SFX + one mix.wav per scene (cached)."""
    from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

    result = AudioMixResult()
    if not project.scenes:
        return result
    engine = FFmpegEngine()

    try:
        music_path, generated = ensure_music_track(project, manager, force=force)
        result.music_track, result.music_generated = music_path, generated
        if asset_repo is not None and generated:
            asset_repo.register(project.id, 0, "music", music_path,
                                sha256=sha256_file(music_path), size_bytes=music_path.stat().st_size)
    except Exception:  # noqa: BLE001 — music is optional per scene
        logger.exception("Music track unavailable — mixing without music")
        music_path = None

    result.sfx_generated = generate_scene_sfx(project, manager, force=force)

    total = len(project.scenes)
    for index, scene in enumerate(project.scenes, start=1):
        mix_path = manager.asset_path(project, scene.scene_id, "mix")
        if not force and mix_path.exists() and mix_path.stat().st_size > 44:
            scene.assets["mix"] = _relative(manager, mix_path, project)
            result.cached += 1
            if on_progress:
                on_progress(index, total, scene.scene_id)
            continue
        try:
            saved = mix_scene_audio(project, scene, music_path=music_path,
                                    output=mix_path, engine=engine)
            scene.assets["mix"] = _relative(manager, saved, project)
            result.mixes.append(saved)
            if scene.status != SceneStatus.DONE:
                scene.status = SceneStatus.AUDIO_READY
            if asset_repo is not None:
                try:
                    asset_repo.register(project.id, scene.scene_id, "mix", saved,
                                        sha256=sha256_file(saved), size_bytes=saved.stat().st_size)
                except Exception:  # noqa: BLE001
                    logger.warning("Scene %03d: mix asset registry skipped", scene.scene_id)
            logger.info("Scene %03d mix ready (%.1fs)", scene.scene_id, wav_duration(saved))
        except Exception as exc:  # noqa: BLE001 — isolate scene failures
            scene.status = SceneStatus.FAILED
            result.failed_scenes.append(scene.scene_id)
            logger.exception("Scene %d audio mix failed: %s", scene.scene_id, exc)
        finally:
            if on_progress:
                on_progress(index, total, scene.scene_id)

    try:
        manager.save(project, autosave=True)
    except Exception:  # noqa: BLE001
        logger.exception("Auto-saving project '%s' after audio mix failed", project.name)
    return result


def _relative(manager: ProjectManager, path: Path, project: Project) -> str:
    """Asset path relative to the project directory (canonical registry form)."""
    try:
        return str(path.relative_to(manager.project_dir(project))).replace("\\", "/")
    except (ValueError, Exception):  # noqa: BLE001 — fall back to absolute
        return str(path)
