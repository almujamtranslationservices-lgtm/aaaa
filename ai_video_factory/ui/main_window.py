"""Main window — sidebar navigation + stacked pages (spec §4)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QStatusBar, QVBoxLayout, QWidget,
)

from ai_video_factory import __version__
from ai_video_factory.core.exceptions import ProjectError
from ai_video_factory.models.project import Project
from ai_video_factory.ui.character_view import CharacterPage
from ai_video_factory.ui.dashboard import DashboardPage, NewProjectDialog
from ai_video_factory.ui.logs_view import LogsPage
from ai_video_factory.ui.project_view import ProjectPage
from ai_video_factory.ui.provider_view import ProviderPage
from ai_video_factory.ui.scene_editor import SceneEditorPage
from ai_video_factory.ui.settings_view import SettingsPage

if TYPE_CHECKING:
    from ai_video_factory.app import AppContext

_NAV_ITEMS = (
    ("🏠  Dashboard", "dashboard"),
    ("🎬  Project", "project"),
    ("🎞  Scenes", "scenes"),
    ("👥  Characters", "characters"),
    ("🧠  AI Providers", "providers"),
    ("⚙  Settings", "settings"),
    ("📜  Logs", "logs"),
)


class MainWindow(QMainWindow):
    """Application shell: sidebar + QStackedWidget + status bar."""

    def __init__(self, context: "AppContext") -> None:
        super().__init__()
        self._ctx = context
        self._project: Project | None = None
        self.setWindowTitle(f"AI Video Factory v{__version__}")
        self.resize(1280, 820)
        self.setMinimumSize(1024, 700)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        # ---- sidebar ----------------------------------------------------
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(228)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 14)
        sidebar_layout.setSpacing(6)

        logo = QLabel("🎬 AI Video Factory")
        logo.setObjectName("AppTitle")
        version = QLabel(f"v{__version__} — free-first pipeline")
        version.setObjectName("AppSubtitle")
        sidebar_layout.addWidget(logo)
        sidebar_layout.addWidget(version)
        sidebar_layout.addSpacing(16)

        self._nav_buttons: dict[str, QPushButton] = {}
        for label, key in _NAV_ITEMS:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            self._nav_buttons[key] = button
            sidebar_layout.addWidget(button)
        sidebar_layout.addStretch(1)

        settings = self._ctx.settings_service.settings
        mode_chip = QLabel("🟢 DEMO MODE" if settings.demo_mode else "PRODUCTION MODE")
        mode_chip.setObjectName("Chip" if settings.demo_mode else "ChipWarn")
        mode_chip.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(mode_chip)
        hint = QLabel("Offline mock providers active —\nno API keys required.")
        hint.setObjectName("SidebarHint")
        if not settings.demo_mode:
            hint.setText("Using real providers from .env")
        hint.setWordWrap(True)
        sidebar_layout.addWidget(hint)

        layout.addWidget(sidebar)

        # ---- pages ------------------------------------------------------
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.dashboard_page = DashboardPage(context)
        self.project_page = ProjectPage(context)
        self.scene_page = SceneEditorPage(context)
        self.character_page = CharacterPage(context)
        self.provider_page = ProviderPage(context)
        self.settings_page = SettingsPage(context)
        self.logs_page = LogsPage(context.bus)

        for page in (self.dashboard_page, self.project_page, self.scene_page,
                     self.character_page, self.provider_page, self.settings_page,
                     self.logs_page):
            self.stack.addWidget(page)

        self._page_keys = ["dashboard", "project", "scenes", "characters",
                           "providers", "settings", "logs"]

        # ---- wiring -----------------------------------------------------
        self.dashboard_page.newProjectRequested.connect(self.open_new_project_dialog)
        self.dashboard_page.openProjectRequested.connect(self.open_project_path)
        self.dashboard_page.navigateRequested.connect(self.switch_page)
        self.project_page.scenesChanged.connect(self.scene_page.refresh_list)
        self.scene_page.scenesChanged.connect(self.project_page._refresh_ui)
        self.character_page.charactersChanged.connect(self._on_characters_changed)

        # ---- status bar -------------------------------------------------
        status = QStatusBar()
        self.setStatusBar(status)
        self._status_project = QLabel("No project")
        self._status_tasks = QLabel("tasks: 0")
        status.addWidget(self._status_project)
        status.addPermanentWidget(self._status_tasks)

        self.switch_page("dashboard")
        self.dashboard_page.refresh()

    # ------------------------------------------------------------- navigation
    def switch_page(self, key: str) -> None:
        if key not in self._page_keys:
            return
        index = self._page_keys.index(key)
        self.stack.setCurrentIndex(index)
        for button_key, button in self._nav_buttons.items():
            button.setChecked(button_key == key)
        if key == "dashboard":
            self.dashboard_page.refresh()
        if key == "providers":
            self.provider_page.refresh()
        if key == "settings":
            self.settings_page.load()

    # ------------------------------------------------------------- projects
    def open_new_project_dialog(self) -> None:
        dialog = NewProjectDialog(self, default_language=self._ctx.settings_service.settings.language)
        if dialog.exec() != NewProjectDialog.Accepted:
            return
        parameters = dialog.parameters()
        try:
            project = self._ctx.project_manager.create_project(**parameters)
        except ProjectError as exc:
            QMessageBox.warning(self, "Could not create project", str(exc))
            return
        self._set_current_project(project)
        self.switch_page("project")

    def open_project_path(self, path: str) -> None:
        from pathlib import Path

        try:
            project = self._ctx.project_manager.load(Path(path))
        except ProjectError as exc:
            QMessageBox.warning(self, "Could not open project", str(exc))
            return
        self._set_current_project(project)
        self.switch_page("project")

    def _set_current_project(self, project: Project) -> None:
        self._project = project
        self.project_page.set_project(project)
        self.scene_page.set_project(project)
        self.character_page.set_project(project)
        self._status_project.setText(f"Project: {project.name} ({project.status.value})")

    def _on_characters_changed(self) -> None:
        """Characters affect the prompts of every scene — refresh dependent views."""
        self.project_page._refresh_ui()

    # ----------------------------------------------------------------- close
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        stats = self._ctx.task_manager.stats()
        active = stats.get("running", 0) + stats.get("pending", 0) + stats.get("retrying", 0)
        if active:
            answer = QMessageBox.question(
                self, "Tasks still running",
                f"{active} background task(s) are still running.\nCancel them and exit?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()
        sys.stdout.flush()
