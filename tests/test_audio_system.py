"""Tests: audio system — engine mixing, ducking behaviour, generators, service.

The ducking test asserts REAL behaviour by measuring segment amplitudes: with a
quiet narrator over loud constant music, the music-only region must be clearly
louder than the during-speech region (the sidechain compressed it).
"""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.media.audio_processor import (
    generate_ambient_music, generate_sfx, segment_peak, wav_duration, wav_info,
    wav_is_valid,
)
from ai_video_factory.models.project import Project, VideoType
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.services.audio_service import (
    duck_ratio_for, ensure_music_track, generate_scene_mixes,
)
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine


def _engine() -> FFmpegEngine:
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    return engine


def _tone_wav(path, *, seconds: float, frequency: int = 440, amplitude: float = 0.6,
              speech_until: float | None = None, rate: int = 22050) -> None:
    """Synthetic audio: constant tone, or narration that talks until *speech_until*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        for n in range(frames):
            t = n / rate
            env = 1.0 if speech_until is None else (1.0 if t < speech_until else 0.0)
            value = int(amplitude * env * math.sin(2 * math.pi * frequency * t) * 32767)
            handle.writeframes(struct.pack("<h", value))


# ----------------------------------------------------------------- engine mix
def test_mix_duration_voices_and_sfx(tmp_path):
    engine = _engine()
    voice = tmp_path / "voice.wav"
    sfx = tmp_path / "ping.wav"
    _tone_wav(voice, seconds=2.0, frequency=220, amplitude=0.5)
    _tone_wav(sfx, seconds=0.5, frequency=1200, amplitude=0.4)

    out = tmp_path / "mix.wav"
    engine.mix_audio(out, voice=voice, sfx=[sfx], duration_s=3.0, music_volume=0.0)
    info = wav_info(out)
    assert wav_is_valid(out)
    assert info["duration_s"] == pytest.approx(3.0, abs=0.15)   # padded to target
    assert info["channels"] == 2                                # stereo bus
    assert segment_peak(out, 2.2, 2.9) < 0.05                   # padded tail is silent


def test_mix_music_only_with_fades(tmp_path):
    engine = _engine()
    music = tmp_path / "music.wav"
    generate_ambient_music(music, duration_s=2.0, seed=5, volume=0.9)
    out = tmp_path / "mix.wav"
    engine.mix_audio(out, music=music, duration_s=4.0, music_volume=0.8,
                     music_fade_in=1.0, music_fade_out=1.0, ducking_enabled=True)
    assert wav_is_valid(out) and wav_duration(out) == pytest.approx(4.0, abs=0.15)
    # Fades: edges clearly quieter than the middle (looped bed keeps playing).
    assert segment_peak(out, 3.5, 3.95) < 0.5 * segment_peak(out, 1.5, 2.5)


def test_mix_rejects_bad_inputs(tmp_path):
    engine = _engine()
    with pytest.raises(Exception):
        engine.mix_audio(tmp_path / "x.wav")                      # nothing to mix
    with pytest.raises(Exception):
        engine.mix_audio(tmp_path / "x.wav", voice=tmp_path / "missing.wav")


# -------------------------------------------------------------- ducking (real)
def test_ducking_compresses_music_during_speech(tmp_path):
    """Quiet narrator (0.25) over loud constant music (0.85):
    during-speech windows must be much quieter than music-only windows."""
    engine = _engine()
    voice = tmp_path / "voice.wav"       # talks 0-1.5s, silent afterwards
    music = tmp_path / "music.wav"       # loud constant tone
    _tone_wav(voice, seconds=4.0, frequency=220, amplitude=0.25, speech_until=1.5)
    _tone_wav(music, seconds=2.0, frequency=660, amplitude=0.85)

    ducked = tmp_path / "ducked.wav"
    engine.mix_audio(ducked, voice=voice, music=music, duration_s=4.0,
                     music_volume=0.9, ducking_enabled=True, duck_ratio=10.0,
                     music_fade_in=0.0, music_fade_out=0.0)
    during_speech = segment_peak(ducked, 0.4, 1.2)       # music ducked under voice
    after_speech = segment_peak(ducked, 2.6, 3.6)        # music released (500ms release)
    assert during_speech > 0.05                          # voice is audible
    assert after_speech > during_speech * 1.6            # ducking really happened

    # Control: with ducking OFF the difference must vanish.
    unducked = tmp_path / "unducked.wav"
    engine.mix_audio(unducked, voice=voice, music=music, duration_s=4.0,
                     music_volume=0.9, ducking_enabled=False,
                     music_fade_in=0.0, music_fade_out=0.0)
    during2 = segment_peak(unducked, 0.4, 1.2)
    after2 = segment_peak(unducked, 2.6, 3.6)
    assert after2 < during2 * 1.15                       # no ducking → similar music


# ------------------------------------------------------------------ generators
def test_ambient_music_deterministic_and_valid(tmp_path):
    first, second, other = (tmp_path / f"{n}.wav" for n in ("a", "b", "c"))
    generate_ambient_music(first, duration_s=3.0, seed=11)
    generate_ambient_music(second, duration_s=3.0, seed=11)
    generate_ambient_music(other, duration_s=3.0, seed=12)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() != other.read_bytes()
    assert wav_is_valid(first) and wav_duration(first) == pytest.approx(3.0, rel=0.01)


def test_sfx_archetypes_differ_and_validate(tmp_path):
    wind = tmp_path / "wind.wav"
    ping = tmp_path / "ping.wav"
    generate_sfx(wind, description="cold wind howling through the trees")
    generate_sfx(ping, description="a bright notification ping")
    assert wav_is_valid(wind) and wav_is_valid(ping)
    assert wind.read_bytes() != ping.read_bytes()
    with pytest.raises(ValueError):
        generate_sfx(tmp_path / "x.wav", description="   ")


def test_duck_ratio_mapping():
    assert duck_ratio_for(0) == 2.0
    assert duck_ratio_for(-6) == pytest.approx(4.0)
    assert duck_ratio_for(-14) == pytest.approx(6.67, abs=0.05)
    assert duck_ratio_for(-120) == 20.0            # clamped


# --------------------------------------------------------------------- service
@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager):
    from ai_video_factory.services.voice_service import generate_scene_voices

    project = Project(name="Audio Mix", idea="idea", video_type=VideoType.CINEMATIC_STORY,
                      target_duration=12, fps=12)
    project_dir = manager._root / "audio-mix"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.settings.music.volume = 0.3
    project.scenes = [
        Scene(scene_id=1, duration=3.0, narration="السرد الأول هنا", sfx="wind",
              status=SceneStatus.AUDIO_READY),
        Scene(scene_id=2, duration=3.0, narration="second narration", status=SceneStatus.AUDIO_READY),
    ]
    manager.save(project)
    generate_scene_voices(project, manager, provider_id="demo")
    return project


def test_full_mix_service(project, manager):
    result = generate_scene_mixes(project, manager)
    assert result.ok and len(result.mixes) == 2
    assert result.music_generated is True and result.music_track is not None
    assert len(result.sfx_generated) == 1                     # only scene 1 has SFX

    project_dir = manager.project_dir(project)
    for i in (1, 2):
        mix = project_dir / "scenes" / f"scene_{i:03d}" / "mix.wav"
        assert mix.exists() and wav_is_valid(mix)
        assert wav_duration(mix) == pytest.approx(3.0, abs=0.3)
        assert project.scenes[i - 1].assets["mix"].endswith(f"scenes/scene_{i:03d}/mix.wav")
    # Scene statuses remain audio-ready (mix is an asset, not a new status).
    assert all(scene.status == SceneStatus.AUDIO_READY for scene in project.scenes)
    # Reload → persisted.
    reloaded = manager.load(project.file_path)
    assert reloaded.scenes[0].assets.get("mix") and reloaded.scenes[0].assets.get("sfx")


def test_mix_cache_and_force(project, manager):
    first = generate_scene_mixes(project, manager)
    assert len(first.mixes) == 2
    second = generate_scene_mixes(project, manager)
    assert second.mixes == [] and second.cached == 2
    forced = generate_scene_mixes(project, manager, force=True)
    assert len(forced.mixes) == 2 and forced.cached == 0


def test_mix_failure_isolated(project, manager, monkeypatch):
    from ai_video_factory.services import audio_service

    original = audio_service.mix_scene_audio

    def fail_scene2(proj, scene, *, music_path, output, engine=None):
        if scene.scene_id == 2:
            raise RuntimeError("mixer exploded")
        return original(proj, scene, music_path=music_path, output=output, engine=engine)

    monkeypatch.setattr(audio_service, "mix_scene_audio", fail_scene2)
    result = generate_scene_mixes(project, manager, force=True)
    assert result.failed_scenes == [2] and len(result.mixes) == 1
    assert project.scenes[1].status == SceneStatus.FAILED


def test_music_track_from_assets(project, manager):
    """A user track placed in assets/music wins over the procedural bed."""
    from ai_video_factory.config.settings import project_root

    track = project_root() / "assets" / "music" / "mybed.wav"
    track.parent.mkdir(parents=True, exist_ok=True)
    try:
        generate_ambient_music(track, duration_s=5.0, seed=99, volume=0.7)
        project.settings.music.track = "mybed.wav"
        path, generated = ensure_music_track(project, manager, force=True)
        assert generated is False and path.exists()
        assert wav_duration(path) == pytest.approx(5.0, rel=0.01)   # user track, not the bed
    finally:
        track.unlink(missing_ok=True)
