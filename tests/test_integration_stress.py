"""Extended integration tests (PHASE 16) — the WHOLE pipeline under stress on
real inputs: real FFmpeg encodes, real SQLite mirrors, cancellation mid-run,
stage failure + resume, and renders with several missing assets at once."""

from __future__ import annotations

import json
import threading

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.database.database import Database
from ai_video_factory.database.repositories import (
    AssetRepository, CharacterRepository, ProjectRepository, SceneRepository,
)
from ai_video_factory.models.project import Project, ProjectStatus, ResolutionPreset, VideoType
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.services.standard_pipeline import build_standard_pipeline, make_context
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine


def _engine_available() -> bool:
    try:
        return FFmpegEngine().available
    except Exception:  # pragma: no cover
        return False


pytestmark = pytest.mark.skipif(not _engine_available(), reason="ffmpeg not available")


class _Recorder:
    def __init__(self, bus: EventBus, name: str) -> None:
        self.events = []
        self._unsub = bus.subscribe(self, event_name=name)

    def __call__(self, event) -> None:
        self.events.append(event)

    def close(self) -> None:
        self._unsub()


@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


def _new_project(manager, *, name: str, idea: str, target: float,
                 scenes: list[Scene] | None = None) -> Project:
    project = Project(name=name, idea=idea, video_type=VideoType.YOUTUBE_VIDEO,
                      resolution=ResolutionPreset.P480, fps=12, target_duration=target)
    project_dir = manager._root / name.lower().replace(" ", "-")
    (project_dir / "scenes").mkdir(parents=True, exist_ok=True)
    project.file_path = project_dir / "project.json"
    if scenes:
        project.scenes = scenes
    manager.save(project)
    return project


# ------------------------------------------------------------------- stress run
def test_full_pipeline_stress_with_db_mirror(bus, settings, manager, tmp_path):
    """Bare idea → final.mp4 with REAL sqlite mirrors and weighted events."""
    db = Database(tmp_path / "stress.sqlite3")
    project_repo = ProjectRepository(db)
    scene_repo = SceneRepository(db)
    asset_repo = AssetRepository(db)
    manager_with_db = ProjectManager(bus, settings, project_repo=project_repo,
                                     scene_repo=scene_repo,
                                     character_repo=CharacterRepository(db))
    project = _new_project(manager_with_db, name="Stress Six",
                           idea="أسرار الصحراء البيضاء: رحلة مصورة من الفجر إلى الغروب",
                           target=12)
    pipeline = build_standard_pipeline(manager_with_db, bus=bus, asset_repo=asset_repo)
    progress = _Recorder(bus, "pipeline.progress")
    try:
        result = pipeline.run(make_context(project, manager_with_db))
    finally:
        progress.close()
    assert result.success, [r.error for r in result.stage_results if r.outcome == "failed"]

    project_dir = manager_with_db.project_dir(project)
    final = project_dir / "output" / "final.mp4"
    assert final.exists() and final.stat().st_size > 5000

    # Real decode of the whole file (not just headers).
    assert FFmpegEngine().validate_video(final)

    # Duration matches the generated timeline within tolerance.
    timeline_total = sum(scene.duration for scene in project.scenes)
    duration = float(FFmpegEngine().probe(final)["format"]["duration"])
    assert duration == pytest.approx(timeline_total, abs=max(2.0, timeline_total * 0.25))

    # The complete publication bundle exists.
    from PIL import Image

    assert (project_dir / "output" / "thumbnail.png").exists()
    with Image.open(project_dir / "output" / "thumbnail.png") as thumb:
        assert thumb.size == (1280, 720)
    assert (project_dir / "subtitles.srt").exists()
    assert (project_dir / "seo.json").exists()
    assert project.status == ProjectStatus.COMPLETED
    assert all(scene.status == SceneStatus.DONE for scene in project.scenes)

    # Weighted progress: monotonic up to exactly 100.
    percents = [event.payload.get("percent", 0.0) for event in progress.events]
    assert percents, "no progress events published"
    assert percents == sorted(percents) or all(
        b >= a - 0.01 for a, b in zip(percents, percents[1:]))
    assert percents[-1] == 100.0

    # SQLite mirror really mirrored the run.
    row = project_repo.get(project.id)
    assert row is not None
    status = row["status"] if not isinstance(row, dict) else row["status"]
    assert status == ProjectStatus.COMPLETED.value
    assert len(scene_repo.list_scenes(project.id)) == len(project.scenes)
    kinds = {asset["kind"] for asset in asset_repo.list_for_project(project.id)}
    assert {"image", "video", "final"} <= kinds
    assert asset_repo.get(project.id, 0, "final") is not None


# ---------------------------------------------------------------- cancel & resume
def test_pipeline_cancel_midway_then_resume(bus, settings, manager):
    project = _new_project(manager, name="Cancel Midway",
                           idea="فيديو قصير عن صناعة الفجر الاصطناعي في الاستوديوهات",
                           target=8)
    pipeline = build_standard_pipeline(manager, bus=bus)
    stop = threading.Event()

    def stop_after_scenes(event) -> None:
        if event.name == "pipeline.stage.completed" and event.payload.get("stage") == "scenes.build":
            stop.set()

    unsubscribe = bus.subscribe(stop_after_scenes, event_name="pipeline.stage.completed")
    try:
        result = pipeline.run(make_context(project, manager), stop_event=stop)
    finally:
        unsubscribe()
    assert result.cancelled or not result.success          # stopped, not completed
    assert project.status != ProjectStatus.COMPLETED

    resumed = pipeline.run(make_context(project, manager))  # caches fill the gap
    assert resumed.success, [r.error for r in resumed.stage_results if r.outcome == "failed"]
    skipped = {r.name for r in resumed.stage_results if r.outcome == "skipped"}
    assert "script.generate" in skipped and "scenes.build" in skipped
    assert (manager.project_dir(project) / "output" / "final.mp4").exists()


# -------------------------------------------------------------- failure & resume
def test_render_failure_aborts_then_resume_completes(bus, settings, manager, monkeypatch):
    scenes = []
    for i in (1, 2, 3):
        scene = Scene(scene_id=i, duration=1.2,
                      narration=f"مشهد رقم {i} بتعليق واضح", visual=f"لقطة رقم {i}")
        if i == 1:
            scene.sfx = "wind"
        scenes.append(scene)
    project = _new_project(manager, name="Fail Then Resume",
                           idea="ثلاث محطات على طريق الفيوم الصحراوي", target=6,
                           scenes=scenes)
    pipeline = build_standard_pipeline(manager, bus=bus)

    def boom(*args, **kwargs):
        raise RuntimeError("renderer exploded (intentional test failure)")

    monkeypatch.setattr("ai_video_factory.services.render_service.render_final_video", boom)
    failed = pipeline.run(make_context(project, manager))
    assert not failed.success
    failed_names = {r.name for r in failed.stage_results if r.outcome == "failed"}
    assert "video.render" in failed_names                 # retried then aborted
    assert project.status != ProjectStatus.COMPLETED

    monkeypatch.undo()                                    # real renderer back
    resumed = pipeline.run(make_context(project, manager))
    assert resumed.success, [r.error for r in resumed.stage_results if r.outcome == "failed"]
    skipped = {r.name for r in resumed.stage_results if r.outcome == "skipped"}
    assert {"script.generate", "images.generate", "voice.generate"} <= skipped
    final = manager.project_dir(project) / "output" / "final.mp4"
    assert final.exists()
    duration = float(FFmpegEngine().probe(final)["format"]["duration"])
    assert duration == pytest.approx(3.6, abs=1.5)        # 3 × 1.2s


# ---------------------------------------------------------- multi-missing assets
def test_render_survives_multiple_missing_assets(bus, settings, manager):
    from ai_video_factory.services.audio_service import generate_scene_mixes
    from ai_video_factory.services.image_service import generate_scene_images
    from ai_video_factory.services.render_service import render_final_video
    from ai_video_factory.services.video_service import generate_scene_videos
    from ai_video_factory.services.voice_service import generate_scene_voices

    scenes = [Scene(scene_id=i, duration=1.2, narration=f"سرد المشهد {i}")
              for i in (1, 2, 3, 4)]
    project = _new_project(manager, name="Multi Missing",
                           idea="أربعة مشاهد تفقد بعض أصولها عمداً", target=6,
                           scenes=scenes)
    generate_scene_images(project, manager, provider_id="demo")
    generate_scene_videos(project, manager, provider_id="demo")
    generate_scene_voices(project, manager, provider_id="demo")
    generate_scene_mixes(project, manager)

    project_dir = manager.project_dir(project)
    (project_dir / "scenes" / "scene_002" / "video.mp4").unlink()          # → Ken Burns
    (project_dir / "scenes" / "scene_003" / "mix.wav").unlink()            # → voice direct
    (project_dir / "scenes" / "scene_003" / "voice.wav").unlink()          # → silence
    (project_dir / "scenes" / "scene_004" / "mix.wav").unlink()            # → voice direct
    (project_dir / "scenes" / "scene_004" / "voice.wav").unlink()          # → silence

    result = render_final_video(project, manager)
    assert result.ok, result.error
    assert result.image_fallback_scenes == [2]
    assert result.silent_scenes == [3, 4]
    duration = float(FFmpegEngine().probe(result.final_path)["format"]["duration"])
    assert duration == pytest.approx(4.8, abs=1.5)        # 4 × 1.2s timeline kept
