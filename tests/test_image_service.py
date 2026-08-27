"""Tests: image service — cache, asset registry, scene status isolation (spec §21)."""

from __future__ import annotations

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.database.database import Database
from ai_video_factory.database.repositories import AssetRepository
from ai_video_factory.models.project import Project, VideoType
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.services.image_service import generate_scene_images
from ai_video_factory.services.scene_service import generate_scene_prompts


@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager):
    project = Project(name="Image Service", idea="idea", video_type=VideoType.CINEMATIC_STORY,
                      target_duration=15, fps=24)
    project_dir = manager._root / "image-service"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.scenes = [
        Scene(scene_id=i, duration=5, narration=f"n{i}",
              visual_description=f"visual {i}", status=SceneStatus.SCRIPTED)
        for i in (1, 2, 3)
    ]
    manager.save(project)
    generate_scene_prompts(project, manager, provider_id="demo")
    return project


def test_generate_images_full_run_with_assets(project, manager, settings):
    from ai_video_factory.database.repositories import ProjectRepository

    database = Database(settings.database_path)
    ProjectRepository(database).upsert_project(
        project, project_dir=manager.project_dir(project), project_file=project.file_path,
    )
    assets = AssetRepository(database)

    progress: list[tuple[int, int, int]] = []
    result = generate_scene_images(
        project, manager, provider_id="demo",
        asset_repo=assets, on_progress=lambda d, t, s: progress.append((d, t, s)),
    )

    assert result.ok and len(result.generated) == 3 and result.skipped_cached == 0
    assert all(scene.status == SceneStatus.IMAGE_READY for scene in project.scenes)

    project_dir = manager.project_dir(project)
    for i in (1, 2, 3):
        image = project_dir / "scenes" / f"scene_{i:03d}" / "image.png"
        assert image.exists() and image.stat().st_size > 0
        row = assets.get(project.id, i, "image")
        assert row is not None and row["sha256"] and row["size_bytes"] == image.stat().st_size

    # Progress reported per scene, ordered.
    assert [p[0] for p in progress] == [1, 2, 3]
    assert progress[-1][1] == 3

    # Assets registered in the project model with relative paths.
    assert project.scenes[0].assets["image"].endswith("scenes/scene_001/image.png")

    # Reload → state persisted.
    reloaded = manager.load(project.file_path)
    assert reloaded.scenes[1].status == SceneStatus.IMAGE_READY
    assert reloaded.scenes[1].assets.get("image")
    database.close()


def test_cache_skips_existing_images(project, manager):
    first = generate_scene_images(project, manager, provider_id="demo")
    assert len(first.generated) == 3

    second = generate_scene_images(project, manager, provider_id="demo")
    assert second.generated == [] and second.skipped_cached == 3

    forced = generate_scene_images(project, manager, provider_id="demo", force=True)
    assert len(forced.generated) == 3 and forced.skipped_cached == 0


def test_failed_scene_is_isolated(project, manager, monkeypatch):
    """A provider failure on one scene marks only that scene FAILED."""
    from ai_video_factory.ai.image.demo import DemoImageProvider

    original = DemoImageProvider.generate
    calls = {"n": 0}

    async def flaky(self, request):
        calls["n"] += 1
        if request.scene_ref == "scene_002":
            raise RuntimeError("provider exploded")
        return await original(self, request)

    monkeypatch.setattr(DemoImageProvider, "generate", flaky)
    result = generate_scene_images(project, manager, provider_id="demo")

    assert result.failed_scenes == [2]
    assert len(result.generated) == 2
    assert project.scenes[1].status == SceneStatus.FAILED
    assert project.scenes[0].status == SceneStatus.IMAGE_READY
    assert calls["n"] == 3


def test_retry_failed_scene_only_regenerates_missing(project, manager, monkeypatch):
    """After a failure, a rerun generates only the missing image (cache rule)."""
    from ai_video_factory.ai.image.demo import DemoImageProvider

    original = DemoImageProvider.generate

    async def fail_scene2(self, request):
        if request.scene_ref == "scene_002":
            raise RuntimeError("boom")
        return await original(self, request)

    monkeypatch.setattr(DemoImageProvider, "generate", fail_scene2)
    first = generate_scene_images(project, manager, provider_id="demo")
    monkeypatch.undo()

    assert first.failed_scenes == [2]
    second = generate_scene_images(project, manager, provider_id="demo")
    assert second.skipped_cached == 2 and len(second.generated) == 1
    assert project.scenes[1].status == SceneStatus.IMAGE_READY
