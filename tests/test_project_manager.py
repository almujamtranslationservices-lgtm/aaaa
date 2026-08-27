"""Tests: ProjectManager — create/save/load, cache layout, summaries, delete."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from ai_video_factory.config.settings import AppSettings
from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.exceptions import ProjectError
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.database.database import Database
from ai_video_factory.database.repositories import ProjectRepository
from ai_video_factory.models.character import Character
from ai_video_factory.models.project import AspectRatio, Project, ProjectStatus, VideoType
from ai_video_factory.models.scene import Scene
from ai_video_factory.utils.file_utils import atomic_write_json

from conftest import Recorder


@pytest.fixture()
def manager(bus: EventBus, settings: AppSettings) -> ProjectManager:
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager: ProjectManager) -> Project:
    return manager.create_project(
        name="قصة الاختفاء",
        idea="قصة اختفاء غامض حدث منذ 100 عام.",
        video_type=VideoType.CINEMATIC_STORY,
        target_duration=45.0,
    )


def test_create_project_builds_layout_and_events(bus, manager, settings):
    recorder = Recorder(bus, "project.created")
    project = manager.create_project(
        name="قصة الاختفاء", idea="فكرة",
        video_type=VideoType.CINEMATIC_STORY, target_duration=45.0,
    )
    project_dir = manager.project_dir(project)
    assert (project_dir / "project.json").exists()
    assert (project_dir / "scenes").is_dir()
    assert project_dir.parent == settings.projects_dir.resolve()
    assert project.status == ProjectStatus.DRAFT
    assert project.aspect_ratio == AspectRatio.R_16_9  # cinematic default
    assert project.fps == 24
    assert recorder.of("project.created")
    recorder.detach()


def test_create_project_rejects_bad_input(manager):
    with pytest.raises(ProjectError):
        manager.create_project(name="   ", idea="x")
    with pytest.raises(ProjectError):
        manager.create_project(name="ok", idea="x", target_duration=1.0)


def test_save_load_roundtrip_with_scenes_and_characters(bus, manager, project):
    project.characters.append(Character(name="Omar", age="35", hair="short black hair"))
    project.scenes = [Scene(scene_id=1, duration=5, narration="نص"), Scene(scene_id=2, duration=6)]
    project.status = ProjectStatus.SCRIPT_READY
    manager.save(project)

    loaded = manager.load(project.file_path)  # type: ignore[arg-type]
    assert loaded.id == project.id
    assert loaded.name == project.name
    assert loaded.status == ProjectStatus.SCRIPT_READY
    assert [scene.scene_id for scene in loaded.scenes] == [1, 2]
    assert loaded.characters[0].hair == "short black hair"
    assert (manager.project_dir(loaded) / "project.json.bak").exists()  # rolling backup


def test_save_creates_backup_on_second_save(manager, project):
    project.scenes = [Scene(scene_id=1)]
    manager.save(project)
    project.name = "Updated"
    manager.save(project)
    backup = project.file_path.parent / "project.json.bak"  # type: ignore[union-attr]
    assert backup.exists()


def test_autosave_publishes_dedicated_event(bus, manager, project):
    recorder = Recorder(bus, "project.autosaved", "project.saved")
    manager.save(project, autosave=True)
    assert recorder.of("project.autosaved") and not recorder.of("project.saved")
    recorder.detach()


def test_load_rejects_missing_and_corrupt(manager, tmp_path):
    with pytest.raises(Exception):
        manager.load(tmp_path / "missing.json")
    corrupt = tmp_path / "corrupt" / "project.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ProjectError):
        manager.load(corrupt)


def test_scene_dir_and_asset_cache(project, manager):
    scene_dir = manager.scene_dir(project, 5)
    assert scene_dir.name == "scene_005"
    assert manager.has_asset(project, 5, "image") is False
    image_path = manager.asset_path(project, 5, "image")
    assert image_path.name == "image.png"
    atomic_write_json(manager.asset_path(project, 5, "prompt"), {"prompt": "x"})
    assert manager.has_asset(project, 5, "prompt") is True
    with pytest.raises(ProjectError):
        manager.asset_path(project, 5, "unknown-kind")


def test_unique_project_slug_on_collision(manager):
    first = manager.create_project(name="Same Name", idea="idea one")
    second = manager.create_project(name="Same Name", idea="idea two")
    assert first.id != second.id
    assert manager.project_dir(first) != manager.project_dir(second)


def test_summaries_via_scan_without_db(bus, manager, settings):
    manager.create_project(name="A", idea="idea a")
    manager.create_project(name="B", idea="idea b")
    summaries = manager.summaries()
    assert len(summaries) == 2
    assert {s.name for s in summaries} == {"A", "B"}


def test_summaries_via_database_mirror(bus, settings):
    database = Database(settings.database_path)
    repo = ProjectRepository(database)
    manager = ProjectManager(bus, settings, project_repo=repo)
    created = manager.create_project(name="DB Mirrored", idea="idea")
    rows = manager.summaries()
    assert len(rows) == 1
    assert rows[0].id == created.id
    assert rows[0].name == "DB Mirrored"
    database.close()


def test_save_mirrors_scenes_and_characters(bus, settings):
    """project.json stays the source of truth; the DB mirrors scenes/characters."""
    from ai_video_factory.database.repositories import CharacterRepository, SceneRepository
    from ai_video_factory.models.scene import Scene

    database = Database(settings.database_path)
    manager = ProjectManager(
        bus, settings,
        project_repo=ProjectRepository(database),
        scene_repo=SceneRepository(database),
        character_repo=CharacterRepository(database),
    )
    project = manager.create_project(name="Mirrored", idea="idea")
    project.characters = [Character(name="Omar", hair="black")]
    project.scenes = [
        Scene(scene_id=1, duration=5, narration="أول", characters=["Omar"]),
        Scene(scene_id=2, duration=6, narration="ثانٍ"),
    ]
    manager.save(project)

    scenes = SceneRepository(database).list_scenes(project.id)
    assert [scene.narration for scene in scenes] == ["أول", "ثانٍ"]
    assert scenes[0].characters == ["Omar"]
    characters = CharacterRepository(database).list_characters(project.id)
    assert [c.name for c in characters] == ["Omar"]
    database.close()


def test_delete_project_removes_db_row_and_files(bus, settings):
    database = Database(settings.database_path)
    repo = ProjectRepository(database)
    manager = ProjectManager(bus, settings, project_repo=repo)
    project = manager.create_project(name="Doomed", idea="bye")
    project_dir = manager.project_dir(project)
    manager.delete(project)
    assert not project_dir.exists()
    assert repo.get(project.id) is None
    database.close()


def test_delete_refuses_paths_outside_projects_root(bus, manager, project, tmp_path):
    project.file_path = tmp_path / "elsewhere" / "project.json"  # simulate tampering
    with pytest.raises(ValueError):
        manager.delete(project, delete_files=True)
