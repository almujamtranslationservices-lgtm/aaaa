"""Tests: smart thumbnail — generator (Arabic shaping, determinism, layout),
service (defaults from SEO/timeline, caching, real backgrounds) and dialog."""

from __future__ import annotations

import json

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.media.thumbnail_generator import (
    format_duration, generate_thumbnail,
)
from ai_video_factory.models.project import Project, VideoType
from ai_video_factory.models.scene import Scene
from ai_video_factory.models.seo import SEOPackage
from ai_video_factory.services.thumbnail_service import (
    generate_smart_thumbnail, load_thumbnail_meta,
)


@pytest.fixture(scope="module")
def no_qt_needed():
    return None


@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager):
    project = Project(name="رحلة الصحراء", idea="استكشاف الصحراء البيضاء بالكاميرا",
                      video_type=VideoType.YOUTUBE_VIDEO, target_duration=12)
    project_dir = manager._root / "thumb-desert"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.scenes = [
        Scene(scene_id=1, duration=4.0, narration="مشهد أول"),
        Scene(scene_id=2, duration=8.0, narration="مشهد ثان"),
    ]
    manager.save(project)
    return project


def _bright_pixels(path) -> int:
    """White title ink — the thumbnail background is always dark."""
    from PIL import Image

    with Image.open(path) as image:
        return sum(1 for pixel in image.convert("L").getdata() if pixel > 210)


# ------------------------------------------------------------------- generator
def test_thumbnail_exact_size_and_deterministic(tmp_path):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    other = tmp_path / "c.png"
    generate_thumbnail(first, title="الصحراء البيضاء", subtitle="رحلة قصيرة", badge="0:12")
    generate_thumbnail(second, title="الصحراء البيضاء", subtitle="رحلة قصيرة", badge="0:12")
    generate_thumbnail(other, title="عنوان مختلف تماما", subtitle="رحلة قصيرة", badge="0:12")
    from PIL import Image

    with Image.open(first) as image:
        assert image.size == (1280, 720)
    assert first.read_bytes() == second.read_bytes()          # deterministic
    assert first.read_bytes() != other.read_bytes()           # content matters


def test_thumbnail_arabic_text_actually_painted(tmp_path):
    """Arabic glyphs must render (bundled Cairo + reshaper), not tofu/blank."""
    plain = tmp_path / "plain.png"
    titled = tmp_path / "titled.png"
    generate_thumbnail(plain, title="ـ", subtitle="", badge="")   # minimal ink
    generate_thumbnail(titled, title="الصحراء البيضاء في الفيوم", subtitle="رحلة", badge="1:00")
    assert _bright_pixels(titled) > _bright_pixels(plain) + 2000   # real ink added


def test_thumbnail_gradient_fallback_and_long_titles(tmp_path):
    out = tmp_path / "grad.png"
    generate_thumbnail(out, title="كلمة " * 40, subtitle="s", badge="9:99")   # no bg, long
    from PIL import Image

    with Image.open(out) as image:
        assert image.size == (1280, 720)                       # never explodes


def test_thumbnail_with_real_background_image(tmp_path):
    from PIL import Image

    bg = tmp_path / "bg.png"
    Image.new("RGB", (300, 500), (10, 120, 200)).save(bg)      # odd aspect on purpose
    out = tmp_path / "with_bg.png"
    generate_thumbnail(out, title="عنوان", background=bg)
    gradient_only = tmp_path / "grad.png"
    generate_thumbnail(gradient_only, title="عنوان")
    with Image.open(out) as image:
        assert image.size == (1280, 720)                       # cover-cropped
    # A real blue background must measurably differ from the gradient fallback.
    with Image.open(out) as a, Image.open(gradient_only) as b:
        assert list(a.convert("RGB").getdata()) != list(b.convert("RGB").getdata())


def test_format_duration():
    assert format_duration(12) == "0:12"
    assert format_duration(75) == "1:15"
    assert format_duration(3671) == "1:01:11"


# --------------------------------------------------------------------- service
def test_service_defaults_from_seo_and_timeline(project, manager):
    project.seo = SEOPackage(title="عنوان سيو جذاب", tags=["x"])
    result = generate_smart_thumbnail(project, manager)
    assert result.ok and not result.cached
    assert result.meta["title"] == "عنوان سيو جذاب"            # SEO wins
    assert result.meta["badge"] == "0:12"                       # 4+8s timeline
    assert result.background_source == "gradient"               # no media yet
    saved = json.loads((manager.project_dir(project) / "output" / "thumbnail.json").read_text())
    assert saved == result.meta


def test_service_cache_and_custom_override(project, manager):
    first = generate_smart_thumbnail(project, manager, title="عنوان مخصص")
    assert first.meta["title"] == "عنوان مخصص"
    cached = generate_smart_thumbnail(project, manager, title="عنوان مخصص")
    assert cached.cached                                          # identical recipe
    forced = generate_smart_thumbnail(project, manager, title="عنوان مخصص", force=True)
    assert not forced.cached and forced.ok
    meta = load_thumbnail_meta(project, manager)
    assert meta is not None and meta["title"] == "عنوان مخصص"


def test_service_uses_scene_image_when_available(project, manager):
    import asyncio

    from ai_video_factory.ai.image.base import ImageRequest
    from ai_video_factory.ai.image.demo import DemoImageProvider

    scene_dir = manager.project_dir(project) / "scenes" / "scene_001"
    scene_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(DemoImageProvider().generate(ImageRequest(
        prompt="x", output_path=scene_dir / "image.png", width=640, height=360)))
    result = generate_smart_thumbnail(project, manager, force=True)
    assert result.ok and result.background_source == "scene-image"


def test_service_uses_final_video_frame(project, manager):
    engine_ok = True
    try:
        from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

        engine_ok = FFmpegEngine().available
    except Exception:  # pragma: no cover
        engine_ok = False
    if not engine_ok:
        pytest.skip("ffmpeg not available")
    import subprocess

    from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

    out_dir = manager.project_dir(project) / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    FFmpegEngine().run([
        "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_dir / "final.mp4"),
    ])
    result = generate_smart_thumbnail(project, manager, force=True)
    assert result.ok and result.background_source == "final-frame"


# ---------------------------------------------------------------------- dialog
def test_thumbnail_dialog_roundtrip(qapp, project, manager):
    from ai_video_factory.ui.thumbnail_dialog import ThumbnailDialog

    result = generate_smart_thumbnail(project, manager, title="عنوان للنافذة")
    dialog = ThumbnailDialog(result.meta, result.path)
    dialog._title.setText("عنوان محرر")
    dialog._subtitle.setText("عنوان فرعي محرر")
    dialog._badge.setText("2:30")
    meta = dialog.meta()
    assert meta == {"title": "عنوان محرر", "subtitle": "عنوان فرعي محرر", "badge": "2:30"}

    dialog._title.setText("")                        # validation: no crash
    dialog._on_save()
    assert dialog.saved_meta is None                 # refused empty title


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
