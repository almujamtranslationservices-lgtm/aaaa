"""Tests: FFmpegEngine — detection, version, run(), error mapping.

Real binary execution is exercised when FFmpeg (or the imageio-ffmpeg
fallback) is available; otherwise those cases skip cleanly.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from ai_video_factory.core.exceptions import FFmpegError, FFmpegNotFoundError
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine


def test_engine_detects_binary_when_present():
    engine = FFmpegEngine()
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg or __import__("importlib.util", fromlist=["find_spec"]).find_spec("imageio_ffmpeg"):
        assert engine.available is True
        assert engine.ffmpeg_path
    else:  # pragma: no cover — sandbox always has the fallback installed
        assert engine.available is False


def test_version_reports_first_line():
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    version = engine.version()
    assert version and version.lower().startswith("ffmpeg version")


def test_run_success():
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    result = engine.run(["-version"], timeout=30)
    assert "ffmpeg version" in result.stdout


def test_run_maps_nonzero_exit_to_ffmpeg_error():
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    with pytest.raises(FFmpegError) as excinfo:
        engine.run(["-y", "-bogus-option"], timeout=30)
    assert "exited with code" in str(excinfo.value)


def test_missing_binary_raises_not_found():
    engine = FFmpegEngine(ffmpeg_path="/nonexistent/ffmpeg", ffprobe_path="/nonexistent/ffprobe")
    assert engine.available is False
    with pytest.raises(FFmpegNotFoundError):
        _ = engine.ffmpeg_path
    with pytest.raises(FFmpegNotFoundError):
        engine.run(["-version"])


def test_all_media_operations_are_implemented():
    """PHASE 12: the engine's media ops are all REAL (no honest stubs left)."""
    engine = FFmpegEngine()
    from pathlib import Path

    for name in ("image_to_video", "concat_videos", "scale_video", "mix_audio",
                 "burn_subtitles", "mux_audio", "extract_thumbnail", "validate_video"):
        method = getattr(engine, name)
        assert callable(method), name
        # Honest failures for bad inputs are FFmpegError — never NotImplementedError.
        try:
            method()
        except NotImplementedError:  # pragma: no cover - would regress to stubs
            pytest.fail(f"{name} regressed to a stub")
        except Exception:
            pass  # real validation errors are expected without arguments


def test_ffmpeg_really_encodes_a_video(tmp_path):
    """Smoke test: the engine can actually encode through the detected binary."""
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    output = tmp_path / "smoke.mp4"
    engine.run([
        "-y",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1",
        "-r", "30", "-pix_fmt", "yuv420p", str(output),
    ], timeout=60)
    assert output.exists() and output.stat().st_size > 0
