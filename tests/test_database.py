"""Tests: SQLite schema, migrations and repositories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_video_factory.core.exceptions import DatabaseError
from ai_video_factory.database.database import SCHEMA_VERSION, Database
from ai_video_factory.database.repositories import (
    AssetRepository,
    CharacterRepository,
    PromptRepository,
    ProjectRepository,
    ProviderRepository,
    RenderJobRepository,
    SceneRepository,
    SettingsRepository,
    TaskRepository,
)
from ai_video_factory.models.character import Character
from ai_video_factory.models.project import (
    AspectRatio, Project, ProjectStatus, ResolutionPreset, VideoType,
)
from ai_video_factory.models.scene import Scene


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


@pytest.fixture()
def project() -> Project:
    return Project(
        name="Repo Test", idea="idea", video_type=VideoType.YOUTUBE_VIDEO,
        aspect_ratio=AspectRatio.R_16_9, resolution=ResolutionPreset.P1080,
        fps=30, target_duration=60,
    )


def test_migration_sets_version_and_is_idempotent(tmp_path):
    path = tmp_path / "migrate.sqlite3"
    first = Database(path)
    version = first.query_one("PRAGMA user_version")[0]
    first.close()
    second = Database(path)  # reopening must not fail or duplicate schema
    tables = {row[0] for row in second.query("SELECT name FROM sqlite_master WHERE type='table'")}
    second.close()
    assert version == SCHEMA_VERSION
    assert {"projects", "scenes", "characters", "assets", "tasks",
            "settings", "providers", "render_jobs", "prompts"} <= tables


def test_project_repository_roundtrip(db, project):
    repo = ProjectRepository(db)
    repo.upsert_project(project, project_dir=Path("/tmp/x"), project_file=Path("/tmp/x/project.json"))
    project.status = ProjectStatus.SCRIPT_READY
    repo.upsert_project(project, project_dir=Path("/tmp/x"), project_file=Path("/tmp/x/project.json"))
    row = repo.get(project.id)
    assert row["name"] == "Repo Test"
    assert row["status"] == "script_ready"
    assert len(repo.list_summaries()) == 1
    repo.update_status(project.id, "completed")
    assert repo.get(project.id)["status"] == "completed"
    repo.delete(project.id)
    assert repo.get(project.id) is None


def test_scene_repository_replace_and_list(db, project):
    ProjectRepository(db).upsert_project(project, project_dir=Path("/p"), project_file=Path("/p/project.json"))
    repo = SceneRepository(db)
    scenes = [
        Scene(scene_id=1, duration=5, narration="أول", characters=["Omar"], assets={"image": "scene_001/image.png"}),
        Scene(scene_id=2, duration=6, narration="ثانٍ", transition="fade"),
    ]
    repo.replace_scenes(project.id, scenes)
    repo.replace_scenes(project.id, scenes[:1])  # replace-all semantics
    restored = repo.list_scenes(project.id)
    assert len(restored) == 1
    assert restored[0].narration == "أول"
    assert restored[0].characters == ["Omar"]
    assert restored[0].assets == {"image": "scene_001/image.png"}


def test_character_repository_upsert_and_list(db, project):
    ProjectRepository(db).upsert_project(project, project_dir=Path("/p"), project_file=Path("/p/project.json"))
    repo = CharacterRepository(db)
    repo.upsert_character(project.id, Character(name="Omar", hair="black", age="35"))
    repo.upsert_character(project.id, Character(name="Omar", hair="grey"))  # update same name
    repo.upsert_character(project.id, Character(name="Sara"))
    characters = repo.list_characters(project.id)
    assert [c.name for c in characters] == ["Omar", "Sara"]
    assert characters[0].hair == "grey"


def test_asset_repository_unique_per_kind(db, project, tmp_path):
    ProjectRepository(db).upsert_project(project, project_dir=Path("/p"), project_file=Path("/p/project.json"))
    repo = AssetRepository(db)
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG fake")
    repo.register(project.id, 1, "image", path, sha256="abc", size_bytes=9)
    repo.register(project.id, 1, "image", path, sha256="def")  # overwrite, not duplicate
    assert len(repo.list_for_project(project.id)) == 1
    assert repo.get(project.id, 1, "image")["sha256"] == "def"
    assert repo.get(project.id, 1, "video") is None


def test_task_repository_upsert_and_pending(db):
    repo = TaskRepository(db)
    repo.upsert_task({"id": "t1", "name": "render", "status": "running", "attempts": 1,
                      "max_retries": 2, "error": None, "result": None, "metadata": {"scene": 3},
                      "created_at": "2026-01-01T00:00:00+00:00", "started_at": None, "finished_at": None})
    repo.upsert_task({"id": "t1", "name": "render", "status": "failed", "attempts": 3,
                      "max_retries": 2, "error": "boom", "result": None, "metadata": {},
                      "created_at": "2026-01-01T00:00:00+00:00", "started_at": None, "finished_at": "x"})
    assert repo.get("t1")["status"] == "failed"
    assert repo.pending() == []  # failed is terminal, not pending
    repo.upsert_task({"id": "t2", "name": "script", "status": "pending", "attempts": 0,
                      "max_retries": 0, "error": None, "result": None, "metadata": {},
                      "created_at": "2026-01-01T00:00:00+00:00", "started_at": None, "finished_at": None})
    assert [row["id"] for row in repo.pending()] == ["t2"]


def test_settings_repository_json_values(db):
    repo = SettingsRepository(db)
    repo.set("theme", {"mode": "dark", "accent": "#ff8800"})
    repo.set("theme", {"mode": "light"})
    assert repo.get("theme") == {"mode": "light"}
    assert repo.get("missing", default=5) == 5
    assert repo.all()["theme"] == {"mode": "light"}


def test_provider_and_render_job_repositories(db, project):
    ProjectRepository(db).upsert_project(project, project_dir=Path("/p"), project_file=Path("/p/project.json"))
    providers = ProviderRepository(db)
    providers.upsert("llm", "ollama", model="llama3.1", endpoint="http://localhost:11434")
    providers.set_status("llm", "ollama", "online")
    row = providers.list("llm")[0]
    assert row["last_status"] == "online"

    jobs = RenderJobRepository(db)
    jobs.create("job1", project.id)
    jobs.update_progress("job1", 42.5, "images.generate")
    jobs.finish("job1", status="completed", output_path="/out/final.mp4")
    rows = [dict(r) for r in db.query("SELECT * FROM render_jobs")]
    assert rows[0]["status"] == "completed" and rows[0]["progress"] == 42.5


def test_prompt_repository_latest(db, project):
    ProjectRepository(db).upsert_project(project, project_dir=Path("/p"), project_file=Path("/p/project.json"))
    repo = PromptRepository(db)
    repo.save(project.id, "script", '{"v":1}', provider="demo")
    repo.save(project.id, "script", '{"v":2}', provider="demo")
    repo.save(project.id, "image", "prompt", scene_id=3)
    assert repo.latest(project.id, "script") == '{"v":2}'
    assert repo.latest(project.id, "image", scene_id=3) == "prompt"


def test_sql_error_wrapped_as_database_error(db):
    with pytest.raises(DatabaseError):
        db.execute("INSERT INTO nonexistent_table VALUES (1)")
