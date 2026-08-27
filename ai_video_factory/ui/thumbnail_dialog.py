"""Thumbnail dialog — live preview + editable title/subtitle/badge."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)
from PySide6.QtGui import QPixmap

logger = logging.getLogger(__name__)

PREVIEW_WIDTH = 640


class ThumbnailDialog(QDialog):
    """Edit the smart-thumbnail recipe; regeneration happens on Save."""

    def __init__(self, meta: dict, thumbnail_path: Path | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Thumbnail — المصغّرة الذكية")
        self.resize(PREVIEW_WIDTH + 40, 640)
        self._meta_result: dict | None = None

        layout = QVBoxLayout(self)

        self._preview = QLabel()
        self._preview.setFixedHeight(round(PREVIEW_WIDTH * 720 / 1280))
        self._preview.setStyleSheet("background: #101018; border-radius: 8px;")
        self._preview.setAlignment(Qt_AlignCenter())
        self._refresh_preview(thumbnail_path)
        layout.addWidget(self._preview)

        form = QFormLayout()
        self._title = QLineEdit(str(meta.get("title", "")))
        self._title.setMaxLength(100)
        self._subtitle = QLineEdit(str(meta.get("subtitle", "")))
        self._subtitle.setMaxLength(90)
        self._badge = QLineEdit(str(meta.get("badge", "")))
        self._badge.setMaxLength(12)
        form.addRow("العنوان:", self._title)
        form.addRow("العنوان الفرعي:", self._subtitle)
        form.addRow("شارة المدة:", self._badge)
        layout.addLayout(form)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #c0392b;")
        layout.addWidget(self._error)

        save = QPushButton("💾 حفظ وإعادة التوليد")
        save.clicked.connect(self._on_save)
        layout.addWidget(save)

    # ------------------------------------------------------------------ helpers
    def _refresh_preview(self, path: Path | None) -> None:
        if path is not None and Path(path).exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._preview.setPixmap(
                    pixmap.scaledToWidth(PREVIEW_WIDTH))
                return
        self._preview.setText("(لا مصغّرة بعد — ستُولَّد عند الحفظ)")

    def _on_save(self) -> None:
        if not self._title.text().strip():
            self._error.setText("العنوان لا يمكن أن يكون فارغاً")
            return
        self._meta_result = self.meta()
        self.accept()

    def meta(self) -> dict:
        return {
            "title": self._title.text().strip(),
            "subtitle": self._subtitle.text().strip(),
            "badge": self._badge.text().strip(),
        }

    @property
    def saved_meta(self) -> dict | None:
        return self._meta_result


def Qt_AlignCenter():
    from PySide6.QtCore import Qt

    return Qt.AlignmentFlag.AlignCenter
