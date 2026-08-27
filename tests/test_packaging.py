"""Tests: packaging & distribution (PHASE 17) — wheel contents, entry points,
font resolution from inside an installed package, and release script/spec."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_declares_distribution_correctly():
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "ai-video-factory"
    assert project["requires-python"] == ">=3.11"
    scripts = project["scripts"]
    assert scripts["ai-video-factory"] == "ai_video_factory.cli:main"
    deps = " ".join(project["dependencies"])
    for critical in ("PySide6", "Pillow", "pydantic", "edge-tts",
                     "imageio-ffmpeg", "arabic-reshaper", "python-bidi"):
        assert critical in deps, critical


def test_fonts_ship_inside_the_package():
    fonts = ROOT / "ai_video_factory" / "assets" / "fonts"
    assert (fonts / "Cairo-Bold.ttf").exists()
    assert (fonts / "Cairo-Regular.ttf").exists()


def test_font_candidates_prefer_packaged_location():
    from ai_video_factory.media.thumbnail_generator import font_candidates

    bold = font_candidates("Cairo-Bold.ttf")
    assert bold[0] == (ROOT / "ai_video_factory" / "assets" / "fonts" / "Cairo-Bold.ttf")
    assert bold[0].exists()                       # works when pip-installed too
    assert bold[1].name == "Cairo-Bold.ttf"       # repo-layout fallback


def test_project_root_frozen_aware():
    """Frozen executables must resolve paths next to the binary, not __file__."""
    from ai_video_factory.config import settings

    assert settings.project_root() == ROOT
    fake = sys                                   # simulate PyInstaller freeze
    original_frozen = getattr(fake, "frozen", None)
    original_executable = fake.executable
    try:
        fake.frozen = True
        fake.executable = str(ROOT / "dist" / "AIVideoFactory" / "AIVideoFactory")
        assert settings.project_root() == Path(fake.executable).parent
    finally:                                     # restore the REAL interpreter
        if original_frozen is None:
            delattr(fake, "frozen")
        else:
            fake.frozen = original_frozen
        fake.executable = original_executable


def test_module_entry_point_runs_outside_repo(tmp_path):
    """`python -m ai_video_factory version` must work from any cwd."""
    import os

    env = {**os.environ, "PYTHONPATH": str(ROOT)}   # package available, foreign cwd
    result = subprocess.run(
        [sys.executable, "-m", "ai_video_factory", "version"],
        capture_output=True, text=True, cwd=str(tmp_path), timeout=120, env=env,
    )
    assert result.returncode == 0
    assert "AI Video Factory" in result.stdout


@pytest.mark.slow
def test_wheel_contains_fonts_and_entry_points(tmp_path):
    """A real wheel build: fonts + entry points inside (the pip distribution)."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(tmp_path)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300,
    )
    assert result.returncode == 0, result.stderr[-400:]
    (wheel_path,) = tmp_path.glob("ai_video_factory-*.whl")
    names = zipfile.ZipFile(wheel_path).namelist()
    assert "ai_video_factory/assets/fonts/Cairo-Bold.ttf" in names
    assert "ai_video_factory/assets/fonts/Cairo-Regular.ttf" in names
    assert any("entry_points.txt" in name for name in names)
    entry_points = next(
        zipfile.ZipFile(wheel_path).read(n).decode()
        for n in names if n.endswith("entry_points.txt"))
    assert "ai-video-factory = ai_video_factory.cli:main" in entry_points


def test_release_spec_and_script_exist_and_honest():
    spec = (ROOT / "release.spec").read_text(encoding="utf-8")
    assert "app.py" in spec and '"assets", "assets"' in spec
    assert "imageio_ffmpeg" in spec                     # static ffmpeg bundled
    script = (ROOT / "scripts" / "build_release.sh").read_text(encoding="utf-8")
    assert "pip wheel" in script or "pip\" wheel" in script or "wheel . --no-deps" in script
    assert "enable-shared" in script                    # honest libpython guard
