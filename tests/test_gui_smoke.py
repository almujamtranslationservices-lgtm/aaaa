"""GUI smoke tests — run the real PySide6 UI headless (offscreen platform).

These instantiate the actual MainWindow, create a project through the real
dialog logic, and generate a script through the real task/event pipeline.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ai_video_factory.app import AppContext, launch_gui  # noqa: E402
from ai_video_factory.models.project import (  # noqa: E402
    AspectRatio, VideoType,
)
from ai_video_factory.ui.dashboard import NewProjectDialog  # noqa: E402
from ai_video_factory.ui.main_window import MainWindow  # noqa: E402
from ai_video_factory.ui.project_view import ProjectPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _wait_until(condition, timeout: float = 8.0, app: QApplication | None = None) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if app is not None:
            app.processEvents()
        if condition():
            return True
        time.sleep(0.03)
    return False


def test_new_project_dialog_defaults(qapp):
    dialog = NewProjectDialog()
    dialog.name_edit.setText("Dialog Test")
    # Switching to YouTube Short must default to 9:16 portrait.
    index = dialog.type_combo.findData(VideoType.YOUTUBE_SHORT)
    dialog.type_combo.setCurrentIndex(index)
    assert dialog.aspect_combo.currentData() == AspectRatio.R_9_16
    assert dialog.fps_combo.currentData() == 30

    params = dialog.parameters()
    assert params["name"] == "Dialog Test"
    assert params["video_type"] == VideoType.YOUTUBE_SHORT
    assert params["aspect_ratio"] == AspectRatio.R_9_16
    assert params["target_duration"] >= 3.0


def test_main_window_pages_and_navigation(tmp_path, qapp):
    context = AppContext(root=tmp_path)
    window = MainWindow(context)
    assert window.stack.count() == 7

    window.switch_page("providers")
    assert window.stack.currentIndex() == 4
    window.switch_page("logs")
    assert window.stack.currentIndex() == 6
    assert window.windowTitle().startswith("AI Video Factory")

    window.close()
    context.close()


def test_full_flow_create_project_and_generate_script(tmp_path, qapp):
    """Dashboard → create project → Generate Script → scenes appear (real run)."""
    context = AppContext(root=tmp_path)
    window = MainWindow(context)

    project = context.project_manager.create_project(
        name="GUI Flow Test", idea="", video_type=VideoType.CINEMATIC_STORY,
        target_duration=25.0,
    )
    window._set_current_project(project)

    page: ProjectPage = window.project_page
    page._idea_edit.setPlainText("قصة اختفاء غامض حدث منذ 100 عام ولم يعرف أحد الحقيقة.")
    page._generate_script()

    assert page._generating_task_id is not None
    assert _wait_until(lambda: project.scenes and len(project.scenes) >= 3,
                       timeout=10.0, app=qapp), "script generation did not complete"

    # Project auto-saved with SCRIPT_READY status and mirrored scenes.
    assert project.status.value == "script_ready"
    mirrored = context.scene_repo.list_scenes(project.id)
    assert len(mirrored) == len(project.scenes)
    summaries = context.project_manager.summaries()
    assert any(s.id == project.id for s in summaries)

    # Scene editor sees the scenes; applying an edit persists it.
    window.scene_page.refresh_list()
    assert window.scene_page._list.count() == len(project.scenes)
    window.scene_page._list.setCurrentRow(0)
    window.scene_page._title_edit.setText("Edited Scene")
    window.scene_page._apply_changes()
    assert project.scenes[0].title == "Edited Scene"

    window.close()
    context.close()


def test_character_bible_page_add_edit_and_mirror(tmp_path, qapp):
    """Character Bible: add a character, fill the sheet, apply → saved + mirrored."""
    context = AppContext(root=tmp_path)
    window = MainWindow(context)

    project = context.project_manager.create_project(name="Characters Test", idea="i")
    window._set_current_project(project)
    window.switch_page("characters")

    page = window.character_page
    page._add_character()                      # creates "New Character"
    assert _wait_until(lambda: page._list.count() == 1, timeout=5.0, app=qapp)
    page._list.setCurrentRow(0)

    page._name_edit.setText("Omar")
    page._field_edits["age"].setText("35")
    page._field_edits["hair"].setText("short black hair")
    page._field_edits["clothes"].setText("dark wool coat")
    page._update_preview()
    assert "35-year-old" in page._preview.text() or "35" in page._preview.text()
    page._apply_changes()

    assert [c.name for c in project.characters] == ["Omar"]
    assert project.characters[0].hair == "short black hair"
    # Mirrored to the database (CharacterRepository).
    mirrored = context.character_repo.list_characters(project.id)
    assert [c.name for c in mirrored] == ["Omar"]
    assert mirrored[0].clothes == "dark wool coat"

    window.close()
    context.close()


def test_build_scene_prompts_button_runs_service(tmp_path, qapp):
    """Build Scene Prompts → per-scene prompt.json files + PROMPTED status."""
    from ai_video_factory.models.scene import Scene, SceneStatus

    context = AppContext(root=tmp_path)
    window = MainWindow(context)
    project = context.project_manager.create_project(
        name="Prompts Flow", idea="idea", target_duration=20.0,
    )
    project.scenes = [
        Scene(scene_id=i, duration=5, narration=f"n{i}",
              visual_description=f"visual {i}", status=SceneStatus.SCRIPTED)
        for i in range(1, 4)
    ]
    context.project_manager.save(project)
    window._set_current_project(project)

    page: ProjectPage = window.project_page
    assert page._prompts_button.isEnabled()
    page._build_scene_prompts()

    assert _wait_until(
        lambda: all(s.status == SceneStatus.PROMPTED for s in project.scenes),
        timeout=10.0, app=qapp), "scene prompt generation did not complete"
    project_dir = context.project_manager.project_dir(project)
    for i in (1, 2, 3):
        assert (project_dir / "scenes" / f"scene_{i:03d}" / "prompt.json").exists()

    window.close()
    context.close()


def test_generate_images_button_produces_real_pngs(tmp_path, qapp):
    """Generate Images (demo provider) → real image.png per scene + thumbnails data."""
    from ai_video_factory.models.scene import Scene, SceneStatus
    from ai_video_factory.services.scene_service import generate_scene_prompts

    context = AppContext(root=tmp_path)
    window = MainWindow(context)
    project = context.project_manager.create_project(
        name="Images Flow", idea="idea", target_duration=15.0,
    )
    project.scenes = [
        Scene(scene_id=i, duration=5, narration=f"n{i}",
              visual_description=f"visual {i}", status=SceneStatus.SCRIPTED)
        for i in range(1, 4)
    ]
    context.project_manager.save(project)
    window._set_current_project(project)
    generate_scene_prompts(project, context.project_manager, provider_id="demo")

    page: ProjectPage = window.project_page
    page._image_provider_combo.setCurrentIndex(0)   # demo
    page._generate_images()
    assert _wait_until(
        lambda: all(s.status == SceneStatus.IMAGE_READY for s in project.scenes),
        timeout=20.0, app=qapp), "image generation did not complete"

    project_dir = context.project_manager.project_dir(project)
    for i in (1, 2, 3):
        image = project_dir / "scenes" / f"scene_{i:03d}" / "image.png"
        assert image.exists() and image.stat().st_size > 0

    # Assets mirrored into the DB registry.
    rows = context.asset_repo.list_for_project(project.id)
    assert {row["kind"] for row in rows} == {"image"}

    # Scene editor exposes a thumbnail pixmap for the selected scene.
    window.switch_page("scenes")
    window.scene_page._list.setCurrentRow(0)
    qapp.processEvents()
    assert not window.scene_page._thumbnail.pixmap().isNull()

    window.close()
    context.close()


def test_launch_gui_boots_and_exits(tmp_path, qapp, monkeypatch):
    """launch_gui() runs the full bootstrap (style, context, window) and exits."""
    monkeypatch.setattr(QApplication, "exec", lambda self=None: 0)
    assert launch_gui(root=tmp_path) == 0
