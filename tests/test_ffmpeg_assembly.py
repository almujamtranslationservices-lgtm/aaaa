"""Tests: FFmpeg engine assembly ops (PHASE 12) — concat / scale / burn / mux /
thumbnail. All assertions are behavioural: real clips probed with ffprobe, and
subtitle burning verified by comparing decoded frame bytes before/after."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

# --------------------------------------------------------------------- helpers
def _engine() -> FFmpegEngine:
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    return engine


def _gradient_png(path, width: int, height: int, seed: int = 0) -> None:
    from PIL import Image

    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 255) // max(1, width - 1),
                            (y * 255) // max(1, height - 1),
                            (seed * 40 + x + y) % 256)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _clip(engine: FFmpegEngine, tmp_path, name: str, *, width: int, height: int,
          seconds: float = 1.0, fps: int = 6, motion: str = "zoom_in", seed: int = 0):
    image = tmp_path / f"{name}.png"
    _gradient_png(image, width, height, seed=seed)
    return engine.image_to_video(image, tmp_path / f"{name}.mp4",
                                 duration=seconds, fps=fps, width=width,
                                 height=height, motion=motion)


def _video_stream(engine: FFmpegEngine, video) -> dict:
    info = engine.probe(video)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    duration = float(info["format"]["duration"])
    return {"width": stream["width"], "height": stream["height"],
            "duration": duration, "stream": stream}


def _tone_wav(path, seconds: float = 1.0) -> None:
    import math

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        for n in range(int(seconds * 22050)):
            handle.writeframes(struct.pack("<h", int(0.5 * math.sin(n * 0.05) * 32767)))


# ---------------------------------------------------------------------- concat
def test_concat_normalizes_mixed_resolutions(tmp_path):
    engine = _engine()
    small = _clip(engine, tmp_path, "small", width=320, height=240, seed=1)
    large = _clip(engine, tmp_path, "large", width=640, height=480, seed=2)
    out = engine.concat_videos([small, large], tmp_path / "concat.mp4")
    info = _video_stream(engine, out)
    assert info["duration"] == pytest.approx(2.0, abs=0.25)
    assert (info["width"], info["height"]) == (320, 240)   # first clip's frame wins


def test_concat_explicit_frame_size(tmp_path):
    engine = _engine()
    clips = [_clip(engine, tmp_path, f"c{i}", width=320, height=240, seed=i) for i in (1, 2, 3)]
    out = engine.concat_videos(clips, tmp_path / "concat.mp4", width=640, height=360, fps=12)
    info = _video_stream(engine, out)
    assert (info["width"], info["height"]) == (640, 360)
    assert info["duration"] == pytest.approx(3.0, abs=0.4)


def test_concat_validates_inputs(tmp_path):
    engine = _engine()
    with pytest.raises(Exception):
        engine.concat_videos([], tmp_path / "x.mp4")
    with pytest.raises(Exception):
        engine.concat_videos([tmp_path / "missing.mp4"], tmp_path / "x.mp4")


# ----------------------------------------------------------------------- scale
def test_scale_video_exact_dimensions(tmp_path):
    engine = _engine()
    clip = _clip(engine, tmp_path, "big", width=640, height=480)
    out = engine.scale_video(clip, tmp_path / "small.mp4", width=320, height=240)
    info = _video_stream(engine, out)
    assert (info["width"], info["height"]) == (320, 240)
    assert info["duration"] == pytest.approx(1.0, abs=0.25)


# ------------------------------------------------------------------------ burn
def test_burn_subtitles_really_paints_pixels(tmp_path):
    engine = _engine()
    clip = _clip(engine, tmp_path, "burn", width=320, height=240, seconds=2.0, seed=7)
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nترجمة حقيقية تُحرق\n", encoding="utf-8")

    burned = engine.burn_subtitles(
        clip, srt, tmp_path / "burned.mp4",
        style={"FontSize": 18, "PrimaryColour": "&H00FFFFFF", "OutlineWidth": 2},
    )
    info = _video_stream(engine, burned)
    assert info["duration"] == pytest.approx(2.0, abs=0.3)          # length preserved

    # REAL behaviour: the mid-clip frame must differ from the original's.
    engine.extract_thumbnail(clip, tmp_path / "before.png", time_s=1.0)
    engine.extract_thumbnail(burned, tmp_path / "after.png", time_s=1.0)
    assert (tmp_path / "before.png").read_bytes() != (tmp_path / "after.png").read_bytes()


def test_burn_rejects_bad_inputs(tmp_path):
    engine = _engine()
    clip = _clip(engine, tmp_path, "b", width=320, height=240)
    with pytest.raises(Exception):
        engine.burn_subtitles(clip, tmp_path / "nope.vtt", tmp_path / "x.mp4")
    with pytest.raises(Exception):
        engine.burn_subtitles(tmp_path / "missing.mp4", tmp_path / "s.srt", tmp_path / "x.mp4")


# ------------------------------------------------------------------------- mux
def test_mux_audio_attaches_an_aac_track(tmp_path):
    engine = _engine()
    clip = _clip(engine, tmp_path, "m", width=320, height=240, seconds=1.5)
    audio = tmp_path / "tone.wav"
    _tone_wav(audio, seconds=1.0)
    out = engine.mux_audio(clip, audio, tmp_path / "muxed.mp4")
    info = engine.probe(out)
    types = {s["codec_type"] for s in info["streams"]}
    assert {"video", "audio"} <= types
    audio_stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert audio_stream["codec_name"] == "aac"


# ------------------------------------------------------------------- thumbnail
def test_extract_thumbnail_frame(tmp_path):
    from PIL import Image

    engine = _engine()
    clip = _clip(engine, tmp_path, "t", width=320, height=240, seconds=1.0, seed=3)
    thumb = engine.extract_thumbnail(clip, tmp_path / "thumb.png", time_s=0.5)
    with Image.open(thumb) as image:
        assert image.size == (320, 240)
        assert image.getpixel((5, 5)) is not None


def test_extract_thumbnail_missing_video(tmp_path):
    engine = _engine()
    with pytest.raises(Exception):
        engine.extract_thumbnail(tmp_path / "missing.mp4", tmp_path / "x.png")


# ---------------------------------------------------------------- filter path
def test_escape_filter_path():
    assert FFmpegEngine._escape_filter_path("/tmp/a b's.vtt".replace("vtt", "srt")) == "/tmp/a b\\'s.srt"
    assert FFmpegEngine._escape_filter_path("C:\\media\\x.srt") == "C\\:\\\\media\\\\x.srt"


# ---------------------------------------------------------------- probe backends
def test_probe_pyav_fallback_same_shape(tmp_path):
    """With the ffprobe binary disabled, probing must still answer via PyAV."""
    pytest.importorskip("av")
    engine = FFmpegEngine(ffprobe_path="/nonexistent/ffprobe")   # disables binary
    assert not Path("/nonexistent/ffprobe").exists()
    assert engine.probe_available                                # PyAV fallback

    clip = _clip(engine, tmp_path, "probe", width=320, height=240, seconds=1.0, fps=6)
    info = engine.probe(clip)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert video["codec_name"] == "h264"
    assert (video["width"], video["height"]) == (320, 240)
    num, _, den = video["avg_frame_rate"].partition("/")
    assert float(num) / float(den or 1) == pytest.approx(6.0)
    assert float(info["format"]["duration"]) == pytest.approx(1.0, abs=0.2)
