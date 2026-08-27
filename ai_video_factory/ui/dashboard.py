"""Dashboard page + New Project dialog (spec §4, §5)."""

from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ai_video_factory import __version__
from ai_video_factory.config.providers import ProviderKind, providers_for
from ai_video_factory.models.project import (
    AspectRatio, ResolutionPreset, VideoType, VIDEO_TYPE_DEFAULTS,
)

_TYPE_LABELS: dict[VideoType, str] = {
    VideoType.YOUTUBE_SHORT: "YouTube Short",
    VideoType.YOUTUBE_VIDEO: "YouTube Video",
    VideoType.TIKTOK: "TikTok",
    VideoType.INSTAGRAM_REEL: "Instagram Reel",
    VideoType.DOCUMENTARY: "Documentary",
    VideoType.CINEMATIC_STORY: "Cinematic Story",
    VideoType.CUSTOM: "Custom",
}

_DURATION_DEFAULTS: dict[VideoType, float] = {
    VideoType.YOUTUBE_SHORT: 45.0,
    VideoType.YOUTUBE_VIDEO: 180.0,
    VideoType.TIKTOK: 30.0,
    VideoType.INSTAGRAM_REEL: 30.0,
    VideoType.DOCUMENTARY: 480.0,
    VideoType.CINEMATIC_STORY: 120.0,
    VideoType.CUSTOM: 60.0,
}


class NewProjectDialog(QDialog):
    """New Project wizard (spec §5) — name, type, aspect, resolution, FPS, duration."""

    def __init__(self, parent: QWidget | None = None, default_language: str = "ar") -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setMinimumWidth(520)
        self.default_language = default_language

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. The Vanishing of 1924")
        form.addRow("Project Name *", self.name_edit)

        self.type_combo = QComboBox()
        for video_type in VideoType:
            self.type_combo.addItem(_TYPE_LABELS[video_type], video_type)
        self.type_combo.currentIndexChanged.connect(self._apply_type_defaults)
        form.addRow("Video Type", self.type_combo)

        self.aspect_combo = QComboBox()
        for aspect in AspectRatio:
            self.aspect_combo.addItem(aspect.value, aspect)
        form.addRow("Aspect Ratio", self.aspect_combo)

        self.resolution_combo = QComboBox()
        for resolution in ResolutionPreset:
            self.resolution_combo.addItem(resolution.value.upper(), resolution)
        self.resolution_combo.setCurrentText("1080P")
        form.addRow("Resolution", self.resolution_combo)

        self.fps_combo = QComboBox()
        for fps in (24, 30, 60):
            self.fps_combo.addItem(f"{fps} FPS", fps)
        form.addRow("FPS", self.fps_combo)

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(3.0, 3600.0)
        self.duration_spin.setDecimals(0)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setSingleStep(5.0)
        form.addRow("Video Duration", self.duration_spin)

        self.idea_edit = QPlainTextEdit()
        self.idea_edit.setPlaceholderText(
            "VIDEO IDEA (optional here — you can also write it in the project page)\n"
            "مثال: قصة اختفاء غامض حدث منذ 100 عام ولم يعرف أحد الحقيقة حتى اليوم."
        )
        self.idea_edit.setMaximumHeight(110)
        form.addRow("Video Idea", self.idea_edit)

        layout.addLayout(form)

        self._hint = QLabel("")
        self._hint.setObjectName("MutedLabel")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create Project")
        buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_type_defaults()

    def _apply_type_defaults(self) -> None:
        """Aspect + FPS + duration defaults follow the selected video type."""
        video_type = self.type_combo.currentData()
        if video_type is None:
            return
        aspect, fps = VIDEO_TYPE_DEFAULTS.get(video_type, (AspectRatio.R_16_9, 30))
        self.aspect_combo.setCurrentText(aspect.value)
        self.fps_combo.setCurrentText(f"{fps} FPS")
        if not self.property("duration_touched"):
            self.duration_spin.setValue(_DURATION_DEFAULTS.get(video_type, 60.0))
        width, height = 1920, 1080
        from ai_video_factory.models.project import resolution_dims
        width, height = resolution_dims(self.resolution_combo.currentData(), aspect)
        self._hint.setText(
            f"Output frame: {self.resolution_combo.currentText().upper()} {aspect.value} → {width}×{height}"
        )

    def parameters(self) -> dict:
        """Validated creation parameters (consumed by ProjectManager)."""
        return {
            "name": self.name_edit.text().strip(),
            "idea": self.idea_edit.toPlainText().strip(),
            "video_type": self.type_combo.currentData(),
            "aspect_ratio": self.aspect_combo.currentData(),
            "resolution": self.resolution_combo.currentData(),
            "fps": self.fps_combo.currentData(),
            "target_duration": self.duration_spin.value(),
            "language": self.default_language,
        }

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Missing name", "Please enter a project name.")
            return
        self.accept()


class DashboardPage(QWidget):
    """Home screen: New / Open / Recent projects + system status."""

    newProjectRequested = Signal()
    openProjectRequested = Signal(str)     # project.json path
    navigateRequested = Signal(str)        # page key: settings/providers/logs

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = context
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ---- hero ------------------------------------------------------
        hero = QFrame()
        hero.setObjectName("Card")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 14, 18, 16)
        title = QLabel("Welcome back 👋")
        title.setObjectName("HeroTitle")
        subtitle = QLabel("Turn an idea into a finished video — script, scenes, visuals, voice and SEO.")
        subtitle.setObjectName("MutedLabel")
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)

        actions = QHBoxLayout()
        new_button = QPushButton("＋  New Project")
        new_button.setObjectName("PrimaryButton")
        new_button.clicked.connect(self.newProjectRequested.emit)
        open_button = QPushButton("📂  Open Project…")
        open_button.clicked.connect(self._browse_project)
        actions.addWidget(new_button)
        actions.addWidget(open_button)
        actions.addStretch(1)
        hero_layout.addLayout(actions)
        root.addWidget(hero)

        # ---- recent + status -------------------------------------------
        middle = QHBoxLayout()
        middle.setSpacing(16)

        recent_card = QFrame()
        recent_card.setObjectName("Card")
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(14, 12, 14, 12)
        recent_header = QHBoxLayout()
        recent_title = QLabel("Recent Projects")
        recent_title.setObjectName("CardTitle")
        refresh_button = QPushButton("⟳")
        refresh_button.setFixedWidth(34)
        refresh_button.setToolTip("Refresh")
        refresh_button.clicked.connect(self.refresh)
        recent_header.addWidget(recent_title)
        recent_header.addStretch(1)
        recent_header.addWidget(refresh_button)
        recent_layout.addLayout(recent_header)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Name", "Status", "Scenes", "Updated"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._open_selected)
        recent_layout.addWidget(self._table)

        hint = QLabel("Double-click a project to open it.")
        hint.setObjectName("MutedLabel")
        recent_layout.addWidget(hint)
        middle.addWidget(recent_card, 3)

        status_card = QFrame()
        status_card.setObjectName("Card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_title = QLabel("System Status")
        status_title.setObjectName("CardTitle")
        status_layout.addWidget(status_title)
        self._status_rows = QVBoxLayout()
        status_layout.addLayout(self._status_rows)
        status_layout.addStretch(1)

        for key, label_text in (
            ("settings", "⚙  Settings"),
            ("providers", "🧠  AI Providers"),
            ("logs", "📜  Logs"),
        ):
            button = QPushButton(label_text)
            button.clicked.connect(lambda _=False, k=key: self.navigateRequested.emit(k))
            status_layout.addWidget(button)
        middle.addWidget(status_card, 2)

        root.addLayout(middle, 1)
        self._status_labels: dict[str, QLabel] = {}

    # ----------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Reload recent projects and the system status card."""
        summaries = self._ctx.project_manager.summaries()
        self._table.setRowCount(len(summaries))
        for row, summary in enumerate(summaries):
            values = [summary.name, summary.status, str(summary.scene_count),
                      (summary.updated_at or "")[:19].replace("T", " ")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, str(summary.project_dir / "project.json"))
                self._table.setItem(row, column, item)
        if not summaries:
            self._table.insertRow(0)
            placeholder = QTableWidgetItem("No projects yet — create your first one!")
            placeholder.setData(Qt.UserRole, "")
            self._table.setItem(0, 0, placeholder)

        implemented = sum(1 for kind in ProviderKind for info in providers_for(kind) if info.implemented)
        planned = sum(1 for kind in ProviderKind for info in providers_for(kind) if not info.implemented)
        ffmpeg_version = self._ctx.ffmpeg.version() if self._ctx.ffmpeg.available else "✗ not found"
        rows = [
            ("Version", f"AI Video Factory v{__version__}"),
            ("Python", platform.python_version()),
            ("FFmpeg", ffmpeg_version.split(" version ")[-1][:40] if self._ctx.ffmpeg.available else ffmpeg_version),
            ("Mode", "🟢 DEMO MODE (offline)" if self._ctx.settings_service.settings.demo_mode else "Production"),
            ("Providers", f"{implemented} implemented · {planned} planned (see AI Providers)"),
            ("Projects", str(self._ctx.settings_service.settings.projects_dir)),
            ("Database", str(self._ctx.settings_service.settings.database_path)),
        ]
        # (re)build the status rows
        while self._status_rows.count():
            item = self._status_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for key, value in rows:
            line = QLabel(f"{key}:  {value}")
            line.setObjectName("MutedLabel")
            line.setWordWrap(True)
            self._status_rows.addWidget(line)

    # ------------------------------------------------------------------ actions
    def _browse_project(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", str(self._ctx.settings_service.settings.projects_dir),
            "AI Video Factory Project (project.json)",
        )
        if path:
            self.openProjectRequested.emit(path)

    def _open_selected(self, index) -> None:
        item = self._table.item(index.row(), 0)
        path = item.data(Qt.UserRole) if item else ""
        if path:
            self.openProjectRequested.emit(path)
