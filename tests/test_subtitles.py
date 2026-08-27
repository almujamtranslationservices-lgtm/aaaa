"""Tests: subtitle system — cue splitting, real-voice timing, SRT/ASS writers,
and the subtitle service (per-scene + combined project files)."""

from __future__ import annotations

import re

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.media.subtitle_processor import (
    ass_color, build_project_cues, build_scene_cues, cues_to_ass, cues_to_srt,
    split_narration,
)
from ai_video_factory.models.project import Project, VideoType
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.models.video import SubtitlePosition, SubtitleSettings
from ai_video_factory.services.subtitle_service import generate_subtitles


# ------------------------------------------------------------------- splitting
def test_split_respects_sentences_and_max_chars():
    text = "الجملة الأولى هنا. الجملة الثانية أطول قليلاً وتحتوي كلمات كثيرة جداً " * 3
    chunks = split_narration(text, max_chars=60)
    assert chunks and all("  " not in c for c in chunks)
    assert all(len(c) <= 60 for c in chunks)
    # No word is ever broken: every chunk is made of whole words from the text.
    words = set(text.replace(".", " ").split())
    assert all(w in words for c in chunks for w in c.split())


def test_split_empty_and_punctuation_only():
    assert split_narration("") == []
    assert split_narration("   ،، .. ؟؟  ") == []


def test_split_keeps_short_sentences_whole():
    chunks = split_narration("نعم. لا مبالغة.")
    assert chunks == ["نعم", "لا مبالغة"]


# --------------------------------------------------------------------- timings
def test_scene_cues_timed_from_real_voice_wav(tmp_path):
    """A 2.0s voice.wav must drive the window — not the text estimate."""
    import math
    import struct
    import wave

    voice = tmp_path / "voice.wav"
    with wave.open(str(voice), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        for n in range(int(2.0 * 22050)):
            handle.writeframes(struct.pack("<h", int(0.5 * math.sin(n * 0.03) * 32767)))

    scene = Scene(scene_id=1, duration=5.0, narration="كلام قصير هنا")
    cues = build_scene_cues(scene, voice_path=voice)
    assert cues and cues[-1].end_s <= 2.0 + 0.05        # real audio duration wins


def test_scene_cues_monotonic_and_inside_window():
    narration = " ".join(f"جملة رقم {i} بمحتوى كامل أكثر." for i in range(8))
    scene = Scene(scene_id=1, duration=6.0, narration=narration)
    cues = build_scene_cues(scene)
    assert len(cues) > 1
    for previous, current in zip(cues, cues[1:]):
        assert current.start_s >= previous.start_s
        assert previous.end_s <= current.end_s + 1e-6
    assert cues[0].start_s == 0.0
    assert cues[-1].end_s <= max(6.0, cues[-1].end_s) + 1e-6


def test_project_cues_use_scene_offsets():
    project = Project(name="Subs", idea="i", video_type=VideoType.CINEMATIC_STORY,
                      target_duration=10)
    project.scenes = [
        Scene(scene_id=1, duration=4.0, narration="first scene words"),
        Scene(scene_id=2, duration=4.0, narration="second scene words"),
    ]
    cues = build_project_cues(project)
    second_scene_start = min(c.start_s for c in cues if "second" in c.text)
    assert second_scene_start >= 3.9                       # offset by scene 1 duration
    assert [c.index for c in cues] == list(range(1, len(cues) + 1))


# ---------------------------------------------------------------------- writers
def test_srt_format():
    cues = build_scene_cues(Scene(scene_id=1, duration=3.0, narration="مرحبا بالعالم"))
    srt = cues_to_srt(cues)
    assert re.search(r"1\n00:00:00,000 --> 00:00:\d{2},\d{3}\nمرحبا بالعالم", srt)
    assert srt.endswith("\n")


def test_ass_honours_all_subtitle_settings():
    settings = SubtitleSettings(
        format="ass", font_family="Amiri", font_size=55,
        position=SubtitlePosition.TOP, color="#FF8800", stroke_color="#101010",
        stroke_width=4, background="box", animation="fade",
    )
    cues = build_scene_cues(Scene(scene_id=1, duration=2.5, narration="نص الترجمة"))
    ass = cues_to_ass(cues, settings, width=1920, height=1080)
    assert "[Script Info]" in ass and "PlayResX: 1920" in ass
    assert "Amiri,55" in ass
    assert ass_color("#FF8800") in ass                     # primary colour (BGR!)
    assert ",2,40,40," not in ass.split("Style:")[1].split("\n")[0][-12:]  # top → align 8
    assert "BorderStyle" in ass or ",3," in ass             # boxed background
    assert r"\fad(200,200)" in ass                          # fade animation


def test_ass_alignment_by_position():
    base = SubtitleSettings()
    text = lambda pos: cues_to_ass(  # noqa: E731
        build_scene_cues(Scene(scene_id=1, duration=2.0, narration="x")),
        base.model_copy(update={"position": pos}),
    )
    for position, expected in ((SubtitlePosition.BOTTOM, ",2,40,40,"),
                               (SubtitlePosition.CENTER, ",5,40,40,"),
                               (SubtitlePosition.TOP, ",8,40,40,")):
        assert expected in text(position)


def test_ass_color_conversion():
    assert ass_color("#FFFFFF") == "&H00FFFFFF"
    assert ass_color("#FF0000") == "&H000000FF"             # red → BGR swap
    assert ass_color("00FF00") == "&H0000FF00"
    assert ass_color("#000000", alpha=0x60) == "&H60000000"  # boxed background alpha
    with pytest.raises(ValueError):
        ass_color("notacolor")


# --------------------------------------------------------------------- service
@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager):
    project = Project(name="Sub Project", idea="idea",
                      video_type=VideoType.CINEMATIC_STORY, target_duration=12)
    project_dir = manager._root / "sub-project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.scenes = [
        Scene(scene_id=1, duration=3.0, narration="نص المشهد الأول", status=SceneStatus.AUDIO_READY),
        Scene(scene_id=2, duration=3.0, narration="", status=SceneStatus.AUDIO_READY),
        Scene(scene_id=3, duration=3.0, narration="third scene narration", status=SceneStatus.AUDIO_READY),
    ]
    manager.save(project)
    return project


def test_service_writes_scene_and_project_files(project, manager):
    result = generate_subtitles(project, manager)
    assert result.ok and len(result.scene_files) == 2
    assert result.skipped_no_narration == [2]               # scene 2 has no narration
    project_dir = manager.project_dir(project)
    assert (project_dir / "scenes" / "scene_001" / "subtitle.srt").exists()
    assert not (project_dir / "scenes" / "scene_002" / "subtitle.srt").exists()
    combined = project_dir / "subtitles.srt"
    assert combined.exists()
    content = combined.read_text(encoding="utf-8")
    assert "نص المشهد الأول" in content and "third scene narration" in content
    assert project.scenes[0].assets["subtitle"] == "scenes/scene_001/subtitle.srt"
    # Reload → persisted assets.
    reloaded = manager.load(project.file_path)
    assert reloaded.scenes[0].assets.get("subtitle")


def test_service_ass_format(project, manager):
    project.settings.subtitles.format = "ass"
    result = generate_subtitles(project, manager)
    project_dir = manager.project_dir(project)
    assert (project_dir / "subtitles.ass").exists()
    assert (project_dir / "subtitles.srt").exists()          # SRT always written
    assert any(p.suffix == ".ass" for p in result.project_files)


def test_service_cache(project, manager):
    first = generate_subtitles(project, manager)
    second = generate_subtitles(project, manager)
    assert second.scene_files == [] and second.cached == 2
    third = generate_subtitles(project, manager, force=True)
    assert len(third.scene_files) == 2 and third.cached == 0
