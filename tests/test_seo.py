"""Tests: SEO system — model normalisation, offline template, LLM path with
fallback, service caching, editable dialog."""

from __future__ import annotations

import json

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.project import Project, VideoType
from ai_video_factory.models.scene import Scene
from ai_video_factory.models.seo import SEOPackage, SEOChapter
from ai_video_factory.services.seo_service import (
    build_template_seo, generate_seo, save_seo,
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager):
    project = Project(name="فيديو الصحراء", idea="رحلة عبر الصحراء البيضاء",
                      video_type=VideoType.YOUTUBE_VIDEO, target_duration=12)
    project_dir = manager._root / "seo-desert"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.scenes = [
        Scene(scene_id=1, duration=4.0, narration="شروق الشمس فوق الكثبان. ضوء ذهبي"),
        Scene(scene_id=2, duration=6.0, narration="الرياح تنحت الأعمدة الجيرية ببطء"),
    ]
    manager.save(project)
    return project


# ---------------------------------------------------------------------- model
def test_seo_model_normalisation():
    pkg = SEOPackage(
        title="عنوان تجريبي",
        tags=["أ", "أ", "b", "c"],
        hashtags=["رحلة  ممتعة", "#جديد", "Travel"],
        chapters=[SEOChapter(start_s=0, title="بداية"), SEOChapter(start_s=5.5, title="نهاية")],
    )
    assert pkg.tags == ["أ", "b", "c"]                    # dedupe, order kept
    assert pkg.hashtags == ["#رحلة_ممتعة", "#جديد", "#Travel"]
    assert pkg.chapters_block.startswith("00:00 بداية")
    assert "00:05 نهاية" in pkg.chapters_block


def test_seo_model_rejects_long_title_and_unsorted_chapters():
    with pytest.raises(Exception):
        SEOPackage(title="x" * 101)
    with pytest.raises(Exception):
        SEOPackage(title="ok", chapters=[
            SEOChapter(start_s=10, title="لاحق"), SEOChapter(start_s=2, title="أبكر")])


def test_tags_budget_enforced():
    tags = [f"tagnumber{i:03d}x" + "y" * 12 for i in range(28)]   # ≤30 items, >500 chars
    pkg = SEOPackage(title="t", tags=tags)
    assert len(pkg.tags) <= 30
    assert sum(len(tag) for tag in pkg.tags) <= 500


# ------------------------------------------------------------- offline template
def test_template_seo_deterministic_and_honest(project):
    first = build_template_seo(project)
    second = build_template_seo(project)
    assert first == second                                 # deterministic
    assert len(first.title) <= 100 and first.title.strip()
    assert first.chapters[0].start_s == 0.0
    assert first.chapters[1].start_s == pytest.approx(4.0)  # real cumulative timeline
    assert first.chapters[1].render().startswith("00:04")
    assert first.tags and first.hashtags and first.hashtags[0].startswith("#")
    keywords = " ".join(first.tags)
    assert "في" not in first.tags and "the" not in first.tags  # stopwords excluded


def test_template_seo_truncates_long_names(project):
    project.name = "ن" * 140
    pkg = build_template_seo(project)
    assert len(pkg.title) <= 100


# --------------------------------------------------------------------- service
def test_generate_seo_demo_caches_and_attaches(project, manager):
    result = generate_seo(project, manager, provider_id="demo")
    assert result.ok and not result.used_fallback
    seo_path = manager.project_dir(project) / "seo.json"
    assert seo_path.exists()
    assert project.seo is not None and project.seo.title == result.package.title

    cached = generate_seo(project, manager, provider_id="demo")
    assert cached.cached and cached.package == result.package

    forced = generate_seo(project, manager, provider_id="demo", force=True)
    assert not forced.cached and forced.ok


def test_save_seo_persists_edits(project, manager):
    generate_seo(project, manager, provider_id="demo")
    edited = project.seo.model_copy(deep=True)
    edited.title = "عنوان معدول بعد التحرير"
    edited.tags = ["صحراء", "فيوم"]
    save_seo(project, manager, edited)

    reloaded = SEOPackage.model_validate_json(
        (manager.project_dir(project) / "seo.json").read_text(encoding="utf-8"))
    assert reloaded.title == edited.title
    project_back = manager.load(project.file_path)
    assert project_back.seo is not None and project_back.seo.title == edited.title


def test_llm_path_success(project, manager, monkeypatch):
    """A working LLM chain answer flows through parsing + validation."""
    from ai_video_factory.ai.llm.base import LLMRequest
    from ai_video_factory.services import script_service

    class FakeChain:
        async def generate_json(self, request: LLMRequest) -> dict:
            assert "SEO" in request.system or "محركات" in request.system
            return {"title": "عنوان من الـ LLM", "description": "وصف جذاب",
                    "tags": ["ذكاء", "فيديو"], "hashtags": ["سيو"],
                    "chapters": [{"start_s": 0, "title": "المقدمة"}]}

    monkeypatch.setattr(script_service, "build_chain", lambda *a, **k: FakeChain())
    result = generate_seo(project, manager, provider_id="openai", force=True)
    assert result.ok and not result.used_fallback
    assert result.package.title == "عنوان من الـ LLM"
    assert result.package.hashtags == ["#سيو"]


def test_llm_failure_falls_back_to_template(project, manager, monkeypatch):
    from ai_video_factory.services import script_service

    def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(script_service, "build_chain", boom)
    result = generate_seo(project, manager, provider_id="openai", force=True)
    assert result.ok and result.used_fallback and result.error
    assert result.package.title                    # template answered
    assert (manager.project_dir(project) / "seo.json").exists()


# ---------------------------------------------------------------------- dialog
def test_seo_dialog_edit_roundtrip(project, manager, qapp):
    from ai_video_factory.ui.seo_dialog import SeoDialog

    generate_seo(project, manager, provider_id="demo")
    dialog = SeoDialog(project.seo)
    dialog._title.setText("عنوان محرر من النافذة")
    dialog._tags.setText("تعديل، وسوم")
    dialog._hashtags.setText("#جديد #آخر")
    dialog._chapters.item(1, 1).setText("عنوان فصل معدل")
    package = dialog.package()
    assert package.title == "عنوان محرر من النافذة"
    assert package.tags == ["تعديل", "وسوم"]
    assert package.hashtags == ["#جديد", "#آخر"]
    assert package.chapters[1].title == "عنوان فصل معدل"
    assert package.chapters[1].start_s == project.seo.chapters[1].start_s  # times locked

    dialog._title.setText("")                     # empty title → inline error, no crash
    dialog._on_save()
    assert dialog.saved_package is None or dialog.saved_package.title
