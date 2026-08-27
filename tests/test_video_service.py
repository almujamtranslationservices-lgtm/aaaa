"""Tests: video service — cache, no-image skips, isolation, statuses (spec §21)."""

from __future__ import annotations

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.database.database import Database
from ai_video_factory.database.repositories import AssetRepository, ProjectRepository
from ai_video_factory.models.project import Project, VideoType
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.services.image_service import generate_scene_images
from ai_video_factory.services.scene_service import generate_scene_prompts
from ai_video_factory.services.video_service import generate_scene_videos
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

pytestmark = pytest.mark.skipif(
    not FFmpegEngine().available, reason="ffmpeg binary required for real video encoding"
)


@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager):
    project = Project(name="Video Service", idea="idea", video_type=VideoType.CINEMATIC_STORY,
                      target_duration=15, fps=12)
    project_dir = manager._root / "video-service"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.scenes = [
        Scene(scene_id=i, duration=1.0, narration=f"n{i}",
              visual_description=f"visual {i}", status=SceneStatus.SCRIPTED)
        for i in (1, 2, 3)
    ]
    manager.save(project)
    generate_scene_prompts(project, manager, provider_id="demo")
    generate_scene_images(project, manager, provider_id="demo")
    return project


def test_generate_videos_full_run_with_assets(project, manager, settings):
    database = Database(settings.database_path)
    ProjectRepository(database).upsert_project(
        project, project_dir=manager.project_dir(project), project_file=project.file_path)
    assets = AssetRepository(database)

    # Re-run images through the registry so both kinds are registered.
    generate_scene_images(project, manager, provider_id="demo", asset_repo=assets, force=True)

    progress: list[int] = []
    result = generate_scene_videos(
        project, manager, provider_id="demo",
        asset_repo=assets, on_progress=lambda d, t, s: progress.append(s),
    )

    assert result.ok and len(result.generated) == 3
    assert all(scene.status == SceneStatus.VIDEO_READY for scene in project.scenes)
    project_dir = manager.project_dir(project)
    for i in (1, 2, 3):
        clip = project_dir / "scenes" / f"scene_{i:03d}" / "video.mp4"
        assert clip.exists() and clip.stat().st_size > 1000
        assert FFmpegEngine().validate_video(clip)      # decodable MP4
    kinds = {row["kind"] for row in assets.list_for_project(project.id)}
    assert kinds == {"image", "video"}
    assert progress == [1, 2, 3]
    database.close()


def test_video_cache_and_force(project, manager):
    first = generate_scene_videos(project, manager, provider_id="demo")
    assert len(first.generated) == 3
    second = generate_scene_videos(project, manager, provider_id="demo")
    assert second.generated == [] and second.skipped_cached == 3
    forced = generate_scene_videos(project, manager, provider_id="demo", force=True)
    assert len(forced.generated) == 3 and forced.skipped_cached == 0


def test_scenes_without_images_are_skipped_not_failed(manager):
    from ai_video_factory.models.project import Project as P

    project = P(name="No Images", idea="i", target_duration=5, fps=12)
    project_dir = manager._root / "no-images"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.scenes = [Scene(scene_id=1, duration=2, narration="n", status=SceneStatus.SCRIPTED)]
    manager.save(project)

    result = generate_scene_videos(project, manager, provider_id="demo")
    assert result.ok and result.skipped_no_image == [1] and result.generated == []
    assert project.scenes[0].status != SceneStatus.FAILED


def test_failed_video_scene_is_isolated_and_retried(project, manager, monkeypatch):
    from ai_video_factory.ai.video.demo import DemoVideoProvider

    original = DemoVideoProvider.generate

    async def fail_scene3(self, request):
        if request.scene_ref == "scene_003":
            raise RuntimeError("encoder exploded")
        return await original(self, request)

    monkeypatch.setattr(DemoVideoProvider, "generate", fail_scene3)
    first = generate_scene_videos(project, manager, provider_id="demo")
    monkeypatch.undo()

    assert first.failed_scenes == [3] and len(first.generated) == 2
    assert project.scenes[2].status == SceneStatus.FAILED

    second = generate_scene_videos(project, manager, provider_id="demo")
    assert second.skipped_cached == 2 and len(second.generated) == 1
    assert project.scenes[2].status == SceneStatus.VIDEO_READY
