"""Tests: voice service — cache, empty-narration skips, isolation, statuses."""

from __future__ import annotations

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.media.audio_processor import wav_is_valid
from ai_video_factory.models.project import Project, VideoType
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.services.voice_service import generate_scene_voices


@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager):
    project = Project(name="Voice Service", idea="idea", video_type=VideoType.CINEMATIC_STORY,
                      target_duration=15, fps=24)
    project_dir = manager._root / "voice-service"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.scenes = [
        Scene(scene_id=1, duration=4, narration="الجملة الأولى من السرد", status=SceneStatus.VIDEO_READY),
        Scene(scene_id=2, duration=4, narration="The second narration line", status=SceneStatus.PROMPTED),
        Scene(scene_id=3, duration=4, narration="", status=SceneStatus.SCRIPTED),  # no narration
    ]
    manager.save(project)
    return project


def test_generate_voices_full_run(project, manager):
    progress: list[int] = []
    result = generate_scene_voices(
        project, manager, provider_id="demo",
        on_progress=lambda done, total, sid: progress.append(sid),
    )

    assert result.ok and len(result.generated) == 2
    assert result.skipped_no_narration == [3]
    # Scenes keep their most-advanced status; the prompted one advances.
    assert project.scenes[0].status == SceneStatus.AUDIO_READY
    assert project.scenes[1].status == SceneStatus.AUDIO_READY

    project_dir = manager.project_dir(project)
    for i in (1, 2):
        voice = project_dir / "scenes" / f"scene_{i:03d}" / "voice.wav"
        assert voice.exists() and wav_is_valid(voice)
        assert project.scenes[i - 1].assets["voice"].endswith(f"scenes/scene_{i:03d}/voice.wav")
    assert not (project_dir / "scenes" / "scene_003" / "voice.wav").exists()
    assert progress == [1, 2, 3]

    reloaded = manager.load(project.file_path)
    assert reloaded.scenes[0].assets.get("voice")


def test_voice_cache_and_force(project, manager):
    first = generate_scene_voices(project, manager, provider_id="demo")
    assert len(first.generated) == 2
    second = generate_scene_voices(project, manager, provider_id="demo")
    assert second.generated == [] and second.skipped_cached == 2
    forced = generate_scene_voices(project, manager, provider_id="demo", force=True)
    assert len(forced.generated) == 2 and forced.skipped_cached == 0


def test_failed_voice_scene_is_isolated_and_retried(project, manager, monkeypatch):
    from ai_video_factory.ai.voice.demo import DemoVoiceProvider

    original = DemoVoiceProvider.synthesize

    async def fail_scene1(self, text, settings, output_path):
        if "الأولى" in text:
            raise RuntimeError("tts exploded")
        return await original(self, text, settings, output_path)

    monkeypatch.setattr(DemoVoiceProvider, "synthesize", fail_scene1)
    first = generate_scene_voices(project, manager, provider_id="demo")
    monkeypatch.undo()

    assert first.failed_scenes == [1] and len(first.generated) == 1
    assert project.scenes[0].status == SceneStatus.FAILED

    second = generate_scene_voices(project, manager, provider_id="demo")
    assert second.skipped_cached == 1 and len(second.generated) == 1
    assert project.scenes[0].status == SceneStatus.AUDIO_READY


def test_voice_settings_flow_to_provider(project, manager, monkeypatch):
    from ai_video_factory.ai.voice.demo import DemoVoiceProvider

    captured: dict = {}
    original = DemoVoiceProvider.synthesize

    async def spy(self, text, settings, output_path):
        captured["settings"] = settings.model_dump()
        return await original(self, text, settings, output_path)

    monkeypatch.setattr(DemoVoiceProvider, "synthesize", spy)
    project.settings.voice.speed = 1.3
    project.settings.voice.voice = "ar-EG-SalmaNeural"
    generate_scene_voices(project, manager, provider_id="demo", force=True)

    assert captured["settings"]["speed"] == 1.3
    assert captured["settings"]["voice"] == "ar-EG-SalmaNeural"
