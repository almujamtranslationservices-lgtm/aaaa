"""Scene editor page — edit, reorder, add and delete scenes (spec §9, §16).

A simple timeline: the scene list on the left (order = playback order),
the editing form on the right. Every change is written back to the project
and auto-saved, so nothing is lost if the app closes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ai_video_factory.core.exceptions import AVFError
from ai_video_factory.models.scene import Scene, SceneStatus, Transition
from ai_video_factory.models.project import Project

if TYPE_CHECKING:
    from ai_video_factory.app import AppContext

_EDITABLE_FIELDS: tuple[str, ...] = (
    "narration", "visual_description", "environment", "action", "camera",
    "lighting", "sfx", "music", "image_prompt", "video_prompt",
)

_STATUS_EMOJI: dict[str, str] = {
    "pending": "▪", "scripted": "✎", "prompted": "🧩", "image_ready": "🖼",
    "video_ready": "🎞", "audio_ready": "🔊", "done": "✅", "failed": "✖",
}


class SceneEditorPage(QWidget):
    """Left: scene timeline. Right: form editor for the selected scene."""

    scenesChanged = Signal()

    def __init__(self, context: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._project: Project | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)

        header = QHBoxLayout()
        title = QLabel("Scenes")
        title.setObjectName("SectionTitle")
        self._project_label = QLabel("No project open")
        self._project_label.setObjectName("MutedLabel")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._project_label)
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)

        # ---- timeline (left) -------------------------------------------
        timeline_box = QGroupBox("Timeline")
        timeline_layout = QVBoxLayout(timeline_box)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._load_selected)
        timeline_layout.addWidget(self._list)

        list_buttons = QHBoxLayout()
        add_button = QPushButton("＋ Add")
        add_button.clicked.connect(self._add_scene)
        delete_button = QPushButton("🗑 Delete")
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self._delete_scene)
        up_button = QPushButton("↑")
        up_button.setFixedWidth(40)
        up_button.clicked.connect(lambda: self._move_scene(-1))
        down_button = QPushButton("↓")
        down_button.setFixedWidth(40)
        down_button.clicked.connect(lambda: self._move_scene(1))
        for widget in (add_button, delete_button):
            list_buttons.addWidget(widget)
        list_buttons.addStretch(1)
        list_buttons.addWidget(up_button)
        list_buttons.addWidget(down_button)
        timeline_layout.addLayout(list_buttons)
        splitter.addWidget(timeline_box)

        # ---- editor (right) --------------------------------------------
        editor_box = QGroupBox("Scene Details")
        editor_layout = QVBoxLayout(editor_box)

        # Generated image thumbnail (loads scenes/scene_XXX/image.png when present).
        self._thumbnail = QLabel("No generated image for this scene yet")
        self._thumbnail.setObjectName("MutedLabel")
        self._thumbnail.setAlignment(Qt.AlignCenter)
        self._thumbnail.setMinimumHeight(140)
        self._thumbnail.setStyleSheet("background-color: #161923; border-radius: 8px;")
        editor_layout.addWidget(self._thumbnail)

        form = QFormLayout()
        editor_layout.addLayout(form)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._title_edit = QLineEdit()
        form.addRow("Title", self._title_edit)

        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setRange(0.5, 120.0)
        self._duration_spin.setDecimals(1)
        self._duration_spin.setSingleStep(0.5)
        self._duration_spin.setSuffix(" s")
        form.addRow("Duration", self._duration_spin)

        self._transition_combo = QComboBox()
        for transition in Transition:
            self._transition_combo.addItem(transition.value, transition)
        form.addRow("Transition", self._transition_combo)

        self._characters_edit = QLineEdit()
        self._characters_edit.setPlaceholderText("Omar, Sara — names from the Character Bible")
        form.addRow("Characters", self._characters_edit)

        self._text_edits: dict[str, QPlainTextEdit] = {}
        field_labels = {
            "narration": "Narration *", "visual_description": "Visual Description",
            "environment": "Environment", "action": "Action", "camera": "Camera",
            "lighting": "Lighting", "sfx": "SFX", "music": "Music",
            "image_prompt": "Image Prompt", "video_prompt": "Video Prompt",
        }
        for field in _EDITABLE_FIELDS:
            edit = QPlainTextEdit()
            edit.setMaximumHeight(64 if field == "narration" else 52)
            self._text_edits[field] = edit
            form.addRow(field_labels[field], edit)

        apply_button = QPushButton("💾  Apply Changes")
        apply_button.setObjectName("PrimaryButton")
        apply_button.clicked.connect(self._apply_changes)
        self._apply_status = QLabel("")
        self._apply_status.setObjectName("MutedLabel")
        footer = QHBoxLayout()
        footer.addWidget(apply_button)
        footer.addWidget(self._apply_status)
        footer.addStretch(1)
        form.addRow(footer)
        splitter.addWidget(editor_box)

        splitter.setSizes([320, 640])
        root.addWidget(splitter, 1)

    # ---------------------------------------------------------------- project
    def set_project(self, project: Project | None) -> None:
        self._project = project
        self._project_label.setText(project.name if project else "No project open")
        self.refresh_list()

    def refresh_list(self) -> None:
        """Rebuild the timeline list from the project (keeps selection)."""
        self._loading = True
        selected_id = self._selected_scene().scene_id if self._selected_scene() else None
        self._list.clear()
        if self._project:
            for scene in self._project.scenes:
                emoji = _STATUS_EMOJI.get(scene.status.value, "▪")
                label = scene.title or scene.status.value
                item = QListWidgetItem(
                    f"{emoji} {scene.scene_id:>3} · {scene.duration:>5.1f}s · {label}"
                )
                item.setData(Qt.UserRole, scene.scene_id)
                item.setToolTip(f"status: {scene.status.value}")
                self._list.addItem(item)
            # reselect
            for row in range(self._list.count()):
                if self._list.item(row).data(Qt.UserRole) == selected_id:
                    self._list.setCurrentRow(row)
                    break
        self._loading = False
        self._update_thumbnail()
        if not self._selected_scene():
            self._clear_form()

    # ----------------------------------------------------------------- editing
    def _selected_scene(self) -> Optional[Scene]:
        project = self._project
        if not project or not self._list.currentItem():
            return None
        scene_id = self._list.currentItem().data(Qt.UserRole)
        return project.scene_by_id(int(scene_id))

    def _load_selected(self, _row: int) -> None:
        if self._loading:
            return
        scene = self._selected_scene()
        if scene is None:
            self._clear_form()
            return
        self._title_edit.setText(scene.title)
        self._duration_spin.setValue(scene.duration)
        self._transition_combo.setCurrentText(scene.transition.value)
        self._characters_edit.setText(", ".join(scene.characters))
        for field in _EDITABLE_FIELDS:
            self._text_edits[field].setPlainText(getattr(scene, field))
        self._update_thumbnail()

    def _update_thumbnail(self) -> None:
        """Show scenes/scene_XXX/image.png for the selected scene (if generated)."""
        scene = self._selected_scene()
        self._thumbnail.setPixmap(QPixmap())
        if scene is None or self._project is None or self._project.file_path is None:
            self._thumbnail.setText("No generated image for this scene yet")
            return
        project_dir = self._project.file_path.parent
        image_path = (
            project_dir / scene.assets["image"]
            if scene.assets.get("image")
            else project_dir / "scenes" / f"scene_{scene.scene_id:03d}" / "image.png"
        )
        if not image_path.exists():
            self._thumbnail.setText("No generated image for this scene yet")
            return
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._thumbnail.setText("Image could not be loaded")
            return
        self._thumbnail.setPixmap(pixmap.scaledToHeight(210, Qt.SmoothTransformation))

    def _clear_form(self) -> None:
        self._title_edit.clear()
        self._duration_spin.setValue(5.0)
        self._transition_combo.setCurrentIndex(0)
        self._characters_edit.clear()
        for edit in self._text_edits.values():
            edit.clear()

    def _apply_changes(self) -> None:
        scene = self._selected_scene()
        if scene is None or self._project is None:
            return
        scene.title = self._title_edit.text().strip()
        scene.duration = self._duration_spin.value()
        # Qt stores str-enums as plain strings in item data — convert back explicitly.
        scene.transition = Transition(self._transition_combo.currentData())
        scene.characters = [name.strip() for name in self._characters_edit.text().split(",") if name.strip()]
        for field in _EDITABLE_FIELDS:
            setattr(scene, field, self._text_edits[field].toPlainText().strip())
        try:
            self._ctx.project_manager.save(self._project, autosave=True)
        except AVFError as exc:
            self._apply_status.setText(f"✖ save failed: {exc}")
            return
        self._apply_status.setText("Saved ✓ (auto-saved to project.json)")
        self.refresh_list()
        self.scenesChanged.emit()

    # --------------------------------------------------------------- list ops
    def _add_scene(self) -> None:
        project = self._project
        if project is None:
            return
        next_id = max((scene.scene_id for scene in project.scenes), default=0) + 1
        project.scenes.append(Scene(scene_id=next_id, title=f"Scene {next_id}", status=SceneStatus.SCRIPTED))
        self._save_and_refresh()

    def _delete_scene(self) -> None:
        project = self._project
        scene = self._selected_scene()
        if project is None or scene is None:
            return
        project.scenes = [item for item in project.scenes if item.scene_id != scene.scene_id]
        self._save_and_refresh()

    def _move_scene(self, offset: int) -> None:
        project = self._project
        scene = self._selected_scene()
        if project is None or scene is None:
            return
        index = next(i for i, item in enumerate(project.scenes) if item.scene_id == scene.scene_id)
        new_index = index + offset
        if 0 <= new_index < len(project.scenes):
            project.scenes[index], project.scenes[new_index] = project.scenes[new_index], project.scenes[index]
            self._save_and_refresh(select_id=scene.scene_id)

    def _save_and_refresh(self, select_id: int | None = None) -> None:
        assert self._project is not None
        try:
            self._ctx.project_manager.save(self._project, autosave=True)
        except AVFError:
            pass
        if select_id is not None:
            for row in range(self._list.count()):
                if self._list.item(row).data(Qt.UserRole) == select_id:
                    self._list.setCurrentRow(row)
        self.refresh_list()
        self.scenesChanged.emit()
