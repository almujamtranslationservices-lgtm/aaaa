"""Editable SEO dialog — publication metadata the user can tune by hand."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog, QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_video_factory.models.seo import SEOPackage, SEOChapter

logger = logging.getLogger(__name__)


class SeoDialog(QDialog):
    """Edit an :class:`SEOPackage`; chapter times stay fixed (monotonic)."""

    def __init__(self, package: SEOPackage, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SEO — بيانات النشر")
        self.resize(560, 620)
        self._original = package
        self._result_package: SEOPackage | None = None

        layout = QVBoxLayout(self)
        grid = QGridLayout()

        grid.addWidget(QLabel("العنوان (≤100):"), 0, 0)
        self._title = QLineEdit(package.title)
        self._title.setMaxLength(100)
        grid.addWidget(self._title, 0, 1)

        grid.addWidget(QLabel("الوصف:"), 1, 0)
        self._description = QPlainTextEdit(package.description)

        grid.addWidget(QLabel("الوسوم (فواصل):"), 2, 0)
        self._tags = QLineEdit(", ".join(package.tags))
        grid.addWidget(self._tags, 2, 1)

        grid.addWidget(QLabel("الهاشتاغات:"), 3, 0)
        self._hashtags = QLineEdit(" ".join(package.hashtags))
        grid.addWidget(self._hashtags, 3, 1)

        layout.addLayout(grid)
        layout.addWidget(QLabel("الفصول (الأوقات من التايم لاين — العناوين قابلة للتحرير):"))
        self._chapters = QTableWidget(len(package.chapters), 2)
        self._chapters.setHorizontalHeaderLabels(["الوقت", "العنوان"])
        self._chapters.horizontalHeader().setStretchLastSection(True)
        for row, chapter in enumerate(package.chapters):
            from PySide6.QtCore import Qt

            time_item = QTableWidgetItem(chapter.timestamp)
            time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._chapters.setItem(row, 0, time_item)
            self._chapters.setItem(row, 1, QTableWidgetItem(chapter.title))
        layout.addWidget(self._chapters, stretch=1)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #c0392b;")
        layout.addWidget(self._error)

        save = QPushButton("💾 حفظ")
        save.clicked.connect(self._on_save)
        layout.addWidget(save)

    # ------------------------------------------------------------------ actions
    def _on_save(self) -> None:
        try:
            package = self.package()
        except Exception as exc:  # noqa: BLE001 — show validation problems inline
            self._error.setText(f"خطأ: {exc}")
            return
        self._result_package = package
        self.accept()

    def package(self) -> SEOPackage:
        """Build the validated package from the dialog fields."""
        chapters: list[SEOChapter] = []
        for row in range(self._chapters.rowCount()):
            title_item = self._chapters.item(row, 1)
            title = (title_item.text().strip() if title_item else "") or f"مشهد {row + 1}"
            chapters.append(
                SEOChapter(start_s=self._original.chapters[row].start_s, title=title[:80]))
        tags = [t.strip() for t in self._tags.text().replace("،", ",").split(",") if t.strip()]
        hashtags = [t.strip() for t in self._hashtags.text().replace("،", " ").replace(",", " ").split() if t.strip()]
        return SEOPackage(
            title=self._title.text().strip() or "فيديو",
            description=self._description.toPlainText().strip()[:4990],
            tags=tags, hashtags=hashtags, chapters=chapters,
            language=self._original.language,
        )

    @property
    def saved_package(self) -> SEOPackage | None:
        return self._result_package
