"""Character Bible page — create and edit the project's characters (spec §8).

The consistency system: every field is structured, and the live preview shows
exactly the description block that will be injected into every image/video
prompt of scenes referencing this character.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ai_video_factory.core.exceptions import AVFError
from ai_video_factory.models.character import Character
from ai_video_factory.models.project import Project

if TYPE_CHECKING:
    from ai_video_factory.app import AppContext

_FIELDS: tuple[tuple[str, str], ...] = (
    ("age", "Age"), ("gender", "Gender"), ("height", "Height"), ("face", "Face"),
    ("hair", "Hair"), ("eyes", "Eyes"), ("skin", "Skin"), ("clothes", "Clothes"),
    ("body", "Body"), ("personality", "Personality"), ("voice", "Voice"),
    ("visual_style", "Visual Style"),
)


class CharacterPage(QWidget):
    """Left: character list. Right: structured editor + live prompt preview."""

    charactersChanged = Signal()

    def __init__(self, context: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        self._project: Project | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)

        header = QHBoxLayout()
        title = QLabel("Character Bible")
        title.setObjectName("SectionTitle")
        subtitle = QLabel("Structured character sheets keep every scene visually consistent.")
        subtitle.setObjectName("MutedLabel")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(subtitle)
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)

        # ---- list --------------------------------------------------------
        list_box = QGroupBox("Characters")
        list_layout = QVBoxLayout(list_box)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._load_selected)
        list_layout.addWidget(self._list)
        list_buttons = QHBoxLayout()
        add_button = QPushButton("＋ New")
        add_button.clicked.connect(self._add_character)
        delete_button = QPushButton("🗑 Delete")
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self._delete_character)
        list_buttons.addWidget(add_button)
        list_buttons.addWidget(delete_button)
        list_buttons.addStretch(1)
        list_layout.addLayout(list_buttons)
        splitter.addWidget(list_box)

        # ---- editor ------------------------------------------------------
        editor_box = QGroupBox("Character Sheet")
        form = QFormLayout(editor_box)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Character name (required)")
        form.addRow("Name *", self._name_edit)

        self._field_edits: dict[str, QLineEdit] = {}
        for attr, label in _FIELDS:
            edit = QLineEdit()
            self._field_edits[attr] = edit
            form.addRow(label, edit)
        for attr, edit in self._field_edits.items():
            edit.textChanged.connect(self._update_preview)

        preview_label = QLabel("Injected prompt block (live):")
        preview_label.setObjectName("MutedLabel")
        self._preview = QLabel("—")
        self._preview.setObjectName("MutedLabel")
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet("font-family: 'DejaVu Sans Mono', monospace; color: #9ecbff;")
        form.addRow(preview_label, self._preview)

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

        splitter.setSizes([300, 660])
        root.addWidget(splitter, 1)

    # ---------------------------------------------------------------- project
    def set_project(self, project: Project | None) -> None:
        self._project = project
        self.refresh_list()

    def refresh_list(self) -> None:
        self._loading = True
        self._list.clear()
        if self._project:
            for character in self._project.characters:
                self._list.addItem(f"👤 {character.name}")
        self._loading = False
        if self._project and self._project.characters:
            self._list.setCurrentRow(0)
        else:
            self._clear_form()

    # ----------------------------------------------------------------- editing
    def _selected(self) -> Character | None:
        if not self._project or self._list.currentRow() < 0:
            return None
        row = self._list.currentRow()
        return self._project.characters[row] if 0 <= row < len(self._project.characters) else None

    def _load_selected(self, row: int) -> None:
        if self._loading:
            return
        character = self._selected()
        if character is None:
            self._clear_form()
            return
        self._name_edit.setText(character.name)
        for attr, edit in self._field_edits.items():
            edit.setText(getattr(character, attr))
        self._update_preview()

    def _clear_form(self) -> None:
        self._name_edit.clear()
        for edit in self._field_edits.values():
            edit.clear()
        self._preview.setText("—")

    def _update_preview(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._preview.setText("—")
            return
        character = Character(
            name=name,
            **{attr: edit.text().strip() for attr, edit in self._field_edits.items()},
        )
        self._preview.setText(character.to_prompt_description())

    # --------------------------------------------------------------- list ops
    def _add_character(self) -> None:
        if self._project is None:
            return
        base = "New Character"
        names = {c.name for c in self._project.characters}
        name = base if base not in names else f"{base} {len(names) + 1}"
        self._project.characters.append(Character(name=name))
        self._save_and_refresh(select_name=name)

    def _delete_character(self) -> None:
        character = self._selected()
        if character is None or self._project is None:
            return
        self._project.characters = [
            c for c in self._project.characters if c.name != character.name
        ]
        self._save_and_refresh()

    def _apply_changes(self) -> None:
        character = self._selected()
        if character is None or self._project is None:
            return
        name = self._name_edit.text().strip()
        if not name:
            self._apply_status.setText("✖ name is required")
            return
        character.name = name
        for attr, edit in self._field_edits.items():
            setattr(character, attr, edit.text().strip())
        self._save_and_refresh(select_name=name)

    def _save_and_refresh(self, select_name: str | None = None) -> None:
        assert self._project is not None
        try:
            self._ctx.project_manager.save(self._project, autosave=True)
            self._apply_status.setText("Saved ✓ (auto-saved + mirrored to database)")
        except AVFError as exc:
            self._apply_status.setText(f"✖ save failed: {exc}")
        self.refresh_list()
        if select_name:
            for row in range(self._list.count()):
                if self._list.item(row).text().endswith(select_name):
                    self._list.setCurrentRow(row)
        self.charactersChanged.emit()
