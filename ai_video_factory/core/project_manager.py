"""Project lifecycle management: create, save, load, autosave, cache layout.

On-disk layout (the cache system — every generated asset is kept so a crash
at scene 6 never destroys the work already done for scenes 1-5)::

    projects/<project-slug>/
        project.json              # full project state (source of truth)
        project.json.bak          # rolling backup written on every save
        scenes/
            scene_001/
                image.png         # generated keyframe
                video.mp4         # image-to-video clip
                voice.wav         # narration
                sfx.wav
                prompt.json       # exact prompts + seeds used (reproducibility)
            scene_002/ …

The SQLite database mirrors this data for fast queries and resume support,
but ``project.json`` always remains authoritative.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_video_factory.config.settings import AppSettings
from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.exceptions import ProjectError, ProjectNotFoundError
from ai_video_factory.models.project import (
    AspectRatio,
    Project,
    ProjectStatus,
    ResolutionPreset,
    VideoType,
    VIDEO_TYPE_DEFAULTS,
)
from ai_video_factory.utils.file_utils import atomic_write_json, backup_file, read_json, rmtree_safe, safe_filename, unique_path

if TYPE_CHECKING:
    from ai_video_factory.database.repositories import (
        CharacterRepository, ProjectRepository, SceneRepository,
    )

logger = logging.getLogger(__name__)

PROJECT_FILE = "project.json"
SCENE_DIR_FORMAT = "scene_{:03d}"

#: Canonical asset filenames inside every ``scenes/scene_XXX/`` directory.
ASSET_FILENAMES: dict[str, str] = {
    "image": "image.png",
    "video": "video.mp4",
    "voice": "voice.wav",
    "sfx": "sfx.wav",
    "music": "music.wav",
    "mix": "mix.wav",
    "subtitle": "subtitle.srt",
    "prompt": "prompt.json",
}


@dataclass
class ProjectSummary:
    """Lightweight project descriptor for dashboards / recent lists."""

    id: str
    name: str
    status: str
    project_dir: Path
    updated_at: str
    scene_count: int = 0


class ProjectManager:
    """High-level API over the ``projects/`` tree and its DB mirror."""

    def __init__(self, bus: EventBus, settings: AppSettings,
                 project_repo: "ProjectRepository | None" = None,
                 scene_repo: "SceneRepository | None" = None,
                 character_repo: "CharacterRepository | None" = None) -> None:
        self._bus = bus
        self._settings = settings
        self._repo = project_repo
        self._scene_repo = scene_repo
        self._character_repo = character_repo
        self._root = settings.projects_dir.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------- creation
    def create_project(
        self,
        *,
        name: str,
        idea: str,
        video_type: VideoType = VideoType.YOUTUBE_VIDEO,
        aspect_ratio: AspectRatio | None = None,
        resolution: ResolutionPreset = ResolutionPreset.P1080,
        fps: int | None = None,
        target_duration: float = 60.0,
        language: str | None = None,
    ) -> Project:
        """Create a new project directory tree and register the project.

        ``aspect_ratio`` / ``fps`` default to sensible values per video type.
        """
        name = (name or "").strip()
        if not name:
            raise ProjectError("Project name must not be empty")
        if not (3.0 <= target_duration <= 3600.0):
            raise ProjectError("target_duration must be between 3 and 3600 seconds")

        default_aspect, default_fps = VIDEO_TYPE_DEFAULTS.get(video_type, (AspectRatio.R_16_9, 30))
        project = Project(
            name=name,
            idea=idea.strip(),
            video_type=video_type,
            aspect_ratio=aspect_ratio or default_aspect,
            resolution=resolution,
            fps=fps or default_fps,
            target_duration=target_duration,
            status=ProjectStatus.DRAFT,
            settings={"language": language or self._settings.language},
        )
        project_dir = unique_path(self._root / safe_filename(name))
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "scenes").mkdir(exist_ok=True)
        project.file_path = project_dir / PROJECT_FILE

        self._write(project)
        self._mirror(project)
        self._bus.publish("project.created", project_id=project.id, name=project.name, path=str(project_dir))
        logger.info("Created project '%s' at %s", project.name, project_dir)
        return project

    # ------------------------------------------------------------ save / load
    def save(self, project: Project, *, autosave: bool = False) -> Path:
        """Persist *project* to ``project.json`` (+ backup) and mirror to DB."""
        project.updated_at = datetime.now(timezone.utc).isoformat()
        if autosave and project.status not in (ProjectStatus.COMPLETED,):
            pass  # autosave never changes status; placeholder for future flags
        path = self._write(project)
        self._mirror(project)
        self._bus.publish(
            "project.autosaved" if autosave else "project.saved",
            project_id=project.id, path=str(path),
        )
        return path

    def load(self, path: Path) -> Project:
        """Load a project from its ``project.json`` file."""
        path = Path(path)
        if not path.exists():
            raise ProjectNotFoundError(f"Project file not found: {path}")
        try:
            data = read_json(path)
            project = Project.model_validate(data)
        except Exception as exc:
            raise ProjectError(f"Corrupted project file {path}: {exc}") from exc
        project.file_path = path
        self._bus.publish("project.opened", project_id=project.id, path=str(path))
        logger.info("Loaded project '%s' from %s", project.name, path)
        return project

    def summaries(self) -> list[ProjectSummary]:
        """Recent projects — from the DB mirror, or by scanning ``projects/``."""
        if self._repo is not None:
            return [
                ProjectSummary(
                    id=row["id"], name=row["name"], status=row["status"],
                    project_dir=Path(row["project_dir"]), updated_at=row["updated_at"],
                )
                for row in self._repo.list_summaries()
            ]
        summaries: list[ProjectSummary] = []
        for path in sorted(self._root.glob(f"*/{PROJECT_FILE}"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                project = self.load(path)
                summaries.append(ProjectSummary(project.id, project.name, project.status.value,
                                                path.parent, project.updated_at, len(project.scenes)))
            except ProjectError:
                logger.warning("Skipping unreadable project file %s", path)
        return summaries

    def delete(self, project: Project | str, *, delete_files: bool = True) -> None:
        """Remove a project from the DB and (optionally) from disk."""
        project_id = project if isinstance(project, str) else project.id
        project_dir: Path | None = None
        if not isinstance(project, str) and project.file_path:
            project_dir = project.file_path.parent
        elif self._repo is not None:
            row = self._repo.get(project_id)
            project_dir = Path(row["project_dir"]) if row else None
        if self._repo is not None:
            self._repo.delete(project_id)
        if delete_files and project_dir is not None:
            rmtree_safe(project_dir, must_contain=self._root)
        self._bus.publish("project.deleted", project_id=project_id)
        logger.info("Deleted project %s (files=%s)", project_id, delete_files)

    # ----------------------------------------------------------- cache layout
    def project_dir(self, project: Project) -> Path:
        if project.file_path is None:
            raise ProjectError("Project has no file path — save it first")
        return project.file_path.parent

    def scene_dir(self, project: Project, scene_number: int) -> Path:
        """Return (and create) ``scenes/scene_XXX`` for *scene_number* (1-based)."""
        path = self.project_dir(project) / "scenes" / SCENE_DIR_FORMAT.format(scene_number)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def asset_path(self, project: Project, scene_number: int, kind: str) -> Path:
        """Canonical path of one asset (``kind`` ∈ ASSET_FILENAMES)."""
        try:
            filename = ASSET_FILENAMES[kind]
        except KeyError as exc:
            raise ProjectError(f"Unknown asset kind '{kind}'. Known: {sorted(ASSET_FILENAMES)}") from exc
        return self.scene_dir(project, scene_number) / filename

    def has_asset(self, project: Project, scene_number: int, kind: str) -> bool:
        """Cache check — ``True`` when the asset file already exists."""
        return self.asset_path(project, scene_number, kind).exists()

    # ---------------------------------------------------------------- exports
    def export_package(self, project: Project, dest_dir: Path) -> Path:  # pragma: no cover — PHASE 13
        """Bundle final_video.mp4 + thumbnail + subtitles + SEO + project.json.

        TODO(PHASE 13): implemented together with the rendering pipeline.
        """
        raise NotImplementedError("export_package is planned for PHASE 13 (rendering & export)")

    # -------------------------------------------------------------- internals
    def _write(self, project: Project) -> Path:
        assert project.file_path is not None
        payload: dict[str, Any] = project.model_dump(mode="json")
        if project.file_path.exists():
            backup_file(project.file_path)
        atomic_write_json(project.file_path, payload)
        return project.file_path

    def _mirror(self, project: Project) -> None:
        if self._repo is None and self._scene_repo is None and self._character_repo is None:
            return
        try:
            if self._repo is not None:
                self._repo.upsert_project(project, project_dir=self.project_dir(project),
                                          project_file=project.file_path or Path())
            if self._scene_repo is not None:
                self._scene_repo.replace_scenes(project.id, project.scenes)
            if self._character_repo is not None:
                self._character_repo.replace_characters(project.id, project.characters)
        except Exception:  # noqa: BLE001 — DB mirroring must never block saving
            logger.exception("Failed to mirror project '%s' to the database", project.name)
