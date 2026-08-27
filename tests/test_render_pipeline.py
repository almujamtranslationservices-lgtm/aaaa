"""Tests: rendering pipeline (PHASE 13) — final assembly + Generate Everything.

The pipeline E2E test runs the REAL chain from a bare idea to a final.mp4
(demo providers, real FFmpeg encodes): script → scenes → prompts → images →
videos → voices → mixes → subtitles → timeline → render → export.
"""

from __future__ import annotations

import json

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.pipeline import PIPELINE_PLAN, PipelineContext
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.project import Project, ProjectStatus, ResolutionPreset, VideoType
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.services.render_service import (
    assemble_timeline, render_final_video,
)
from ai_video_factory.services.standard_pipeline import build_standard_pipeline, make_context
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine, FFmpegNotFoundError


def _engine() -> FFmpegEngine:
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    return engine


def _probe(engine, path):
    info = engine.probe(path)
    streams = {s["codec_type"]: s for s in info["streams"]}
    return float(info["format"]["duration"]), streams


# ------------------------------------------------------------- engine: audio concat
def test_concat_audio_pads_and_trims_to_durations(tmp_path):
    import math
    import struct
    import wave

    engine = _engine()

    def tone(path, seconds):
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            for n in range(int(seconds * 22050)):
                handle.writeframes(struct.pack("<h", int(0.5 * math.sin(n * 0.05) * 32767)))

    tone(tmp_path / "a.wav", 2.0)      # longer than its slot → trimmed
    tone(tmp_path / "b.wav", 0.5)      # shorter than its slot → padded
    out = engine.concat_audio([tmp_path / "a.wav", tmp_path / "b.wav"],
                              tmp_path / "out.wav", durations_s=[1.0, 1.5])
    from ai_video_factory.media.audio_processor import wav_duration
    assert wav_duration(out) == pytest.approx(2.5, abs=0.1)

    with pytest.raises(Exception):
        engine.concat_audio([], tmp_path / "x.wav")
    with pytest.raises(Exception):
        engine.concat_audio([tmp_path / "a.wav"], tmp_path / "x.wav", durations_s=[1.0, 2.0])


# ---------------------------------------------------------------- service fixtures
@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


def _mini_project(manager, *, name="Render E2E") -> Project:
    project = Project(name=name, idea="فكرة فيديو تجريبية كاملة",
                      video_type=VideoType.YOUTUBE_VIDEO,
                      resolution=ResolutionPreset.P480, fps=12, target_duration=12)
    project_dir = manager._root / name.lower().replace(" ", "-")
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.scenes = [
        Scene(scene_id=1, duration=1.6, narration="مشهد أول كامل", sfx="wind",
              visual="غرفة قديمة"),
        Scene(scene_id=2, duration=1.6, narration="second scene narration",
              visual="a bright street"),
    ]
    manager.save(project)
    return project


def _build_assets(project, manager):
    """Run the real demo services: images → videos → voices → mixes → subs."""
    from ai_video_factory.services.audio_service import generate_scene_mixes
    from ai_video_factory.services.image_service import generate_scene_images
    from ai_video_factory.services.subtitle_service import generate_subtitles
    from ai_video_factory.services.video_service import generate_scene_videos
    from ai_video_factory.services.voice_service import generate_scene_voices

    generate_scene_images(project, manager, provider_id="demo")
    generate_scene_videos(project, manager, provider_id="demo")
    generate_scene_voices(project, manager, provider_id="demo")
    generate_scene_mixes(project, manager)
    generate_subtitles(project, manager)


# ------------------------------------------------------------------- render tests
def test_render_final_video_full_chain(tmp_path, manager):
    _engine()
    project = _mini_project(manager)
    _build_assets(project, manager)

    progress: list[float] = []
    result = render_final_video(project, manager,
                                on_progress=lambda f, m: progress.append(f))
    assert result.ok, result.error
    final = manager.project_dir(project) / "output" / "final.mp4"
    assert result.final_path == final and final.exists()
    assert result.burned_subtitles and not result.image_fallback_scenes
    assert progress and progress[-1] == 1.0

    engine = FFmpegEngine()
    duration, streams = _probe(engine, final)
    assert duration == pytest.approx(3.2, abs=0.8)              # 2 × 1.6s scenes
    assert "video" in streams and "audio" in streams            # muxed track
    assert streams["audio"]["codec_name"] == "aac"
    assert (streams["video"]["width"], streams["video"]["height"]) == \
        (project.width, project.height)                    # frame honoured exactly
    assert (manager.project_dir(project) / "output" / "thumbnail.png").exists()
    assert project.status == ProjectStatus.COMPLETED
    assert all(scene.status == SceneStatus.DONE for scene in project.scenes)

    # Cached fast path: a second render without force must not re-encode.
    second = render_final_video(project, manager)
    assert second.cached and second.ok


def test_render_survives_missing_video_and_missing_audio(tmp_path, manager):
    _engine()
    project = _mini_project(manager, name="Partial Render")
    _build_assets(project, manager)
    project_dir = manager.project_dir(project)

    (project_dir / "scenes" / "scene_001" / "video.mp4").unlink()   # image fallback
    (project_dir / "scenes" / "scene_002" / "mix.wav").unlink()     # silence fill
    (project_dir / "scenes" / "scene_002" / "voice.wav").unlink()

    result = render_final_video(project, manager, force=True)
    assert result.ok, result.error
    assert result.image_fallback_scenes == [1]
    assert result.silent_scenes == [2]
    assert result.final_path is not None and result.final_path.exists()


def test_render_fails_cleanly_without_any_media(tmp_path, manager):
    _engine()
    project = _mini_project(manager, name="Empty Render")
    result = render_final_video(project, manager)
    assert not result.ok
    assert result.error


def test_assemble_timeline_prefers_video(tmp_path, manager):
    project = _mini_project(manager, name="Timeline")
    _build_assets(project, manager)
    items = assemble_timeline(project, manager)
    assert [item.scene_id for item in items] == [1, 2]
    assert all(item.video_path is not None for item in items)
    assert items[0].start_s == 0.0
    assert items[1].start_s == pytest.approx(items[0].duration_s)


def test_export_package_bundles_outputs(tmp_path, manager):
    _engine()
    project = _mini_project(manager, name="Export Pkg")
    _build_assets(project, manager)
    result = render_final_video(project, manager)
    assert result.ok
    dest = tmp_path / "bundle"
    exported = manager.export_package(project, dest)
    assert (exported / "final.mp4").exists()
    assert (exported / "project.json").exists()
    assert (exported / "subtitles.srt").exists()
    assert json.loads((exported / "project.json").read_text(encoding="utf-8"))["name"] == "Export Pkg"


def test_export_package_requires_render(manager):
    project = _mini_project(manager, name="No Render")
    with pytest.raises(Exception):
        manager.export_package(project, manager._root / "no-render-dest")


# ------------------------------------------------------- full pipeline (E2E!)
def test_standard_pipeline_from_idea_to_final(bus, settings):
    """THE test: bare idea → final.mp4 through every real stage."""
    _engine()
    manager = ProjectManager(bus, settings)
    project = Project(name="Pipeline E2E", idea="رحلة قصيرة عبر الصحراء البيضاء",
                      video_type=VideoType.YOUTUBE_VIDEO,
                      resolution=ResolutionPreset.P480, fps=12, target_duration=10)
    project_dir = manager._root / "pipeline-e2e"
    project_dir.mkdir(parents=True, exist_ok=True)
    project.file_path = project_dir / "project.json"
    manager.save(project)

    pipeline = build_standard_pipeline(manager, bus=bus)
    plan_names = {name for name, _, phase in PIPELINE_PLAN if phase <= 15}
    built_names = {stage.name for stage in pipeline._stages}
    assert built_names <= plan_names                      # documented plan only
    assert {"script.generate", "images.generate", "video.render",
            "seo.generate", "export.final"} <= built_names

    result = pipeline.run(make_context(project, manager))
    assert result.success, [r.error for r in result.stage_results if r.outcome == "failed"]
    final = project_dir / "output" / "final.mp4"
    assert final.exists() and final.stat().st_size > 1000
    assert project.status == ProjectStatus.COMPLETED
    assert all(scene.status == SceneStatus.DONE for scene in project.scenes)
    info = json.loads((project_dir / "output" / "render_info.json").read_text())
    assert info["final"].endswith("final.mp4") and info["scenes"] >= 1
    seo = json.loads((project_dir / "seo.json").read_text(encoding="utf-8"))
    assert seo["title"] and seo["chapters"]                # SEO stage ran too
    from PIL import Image
    with Image.open(project_dir / "output" / "thumbnail.png") as thumb:
        assert thumb.size == (1280, 720)                   # smart thumbnail stage

    engine = FFmpegEngine()
    duration, streams = _probe(engine, final)
    assert duration >= 2.0
    assert {"video", "audio"} <= set(streams)

    # RESUME: re-running skips finished stages via caches and stays green.
    second = pipeline.run(make_context(project, manager))
    assert second.success
    skipped = {r.name for r in second.stage_results if r.outcome == "skipped"}
    assert "script.generate" in skipped                  # scenes already exist


def test_pipeline_weights_match_documented_plan(bus, settings):
    manager = ProjectManager(bus, settings)
    pipeline = build_standard_pipeline(manager, bus=bus)
    plan_weights = {name: weight for name, weight, _ in PIPELINE_PLAN}
    for stage in pipeline._stages:
        assert stage.weight == plan_weights[stage.name]
