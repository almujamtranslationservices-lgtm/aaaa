"""Application composition root — wires every layer together (DI container).

GUI-free by design: ``AppContext`` can power the GUI, a future batch worker or
tests. ``launch_gui()`` is the only function that touches Qt.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from ai_video_factory import APP_NAME, __version__
from ai_video_factory.config.settings import AppSettings, SettingsService
from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.logger import setup_logging
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.core.task_manager import TaskManager
from ai_video_factory.database.database import Database
from ai_video_factory.database.repositories import (
    AssetRepository, CharacterRepository, ProjectRepository, ProviderRepository,
    SceneRepository, TaskRepository,
)
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine

logger = logging.getLogger(__name__)


class AppContext:
    """Owns the bus, settings, database, repositories, task & project managers."""

    def __init__(self, root: Path | None = None) -> None:
        self.bus = EventBus()
        self.settings_service = SettingsService(root=root)
        settings = self.settings_service.settings
        setup_logging(settings.logs_dir, level=settings.log_level, bus=self.bus)

        self.database = Database(settings.database_path)
        self.project_repo = ProjectRepository(self.database)
        self.scene_repo = SceneRepository(self.database)
        self.character_repo = CharacterRepository(self.database)
        self.asset_repo = AssetRepository(self.database)
        self.task_repo = TaskRepository(self.database)
        self.provider_repo = ProviderRepository(self.database)

        self.task_manager = TaskManager(
            self.bus,
            max_workers=settings.max_parallel_tasks,
            persistence=self.task_repo,
        )
        self.project_manager = ProjectManager(
            self.bus, settings,
            project_repo=self.project_repo,
            scene_repo=self.scene_repo,
            character_repo=self.character_repo,
        )
        self.ffmpeg = FFmpegEngine()
        logger.info("%s v%s context ready (demo_mode=%s, providers=%s)",
                    APP_NAME, __version__, settings.demo_mode, settings.providers.model_dump())

    @property
    def settings(self) -> AppSettings:
        return self.settings_service.settings

    def provider_model(self, kind_value: str, provider_id: str) -> str | None:
        """Per-provider model override: DB (AI Providers page) → env → None."""
        for entry in self.provider_repo.list(kind_value):
            if entry["provider_id"] == provider_id and entry["model"]:
                return entry["model"]
        return os.environ.get(f"{provider_id.upper()}_MODEL")

    def close(self) -> None:
        """Stop accepting tasks and close the database (idempotent-ish)."""
        try:
            self.task_manager.shutdown(wait=True)
        except Exception:  # noqa: BLE001 — shutdown must never raise at exit
            logger.exception("TaskManager shutdown error")
        try:
            self.database.close()
        except Exception:  # noqa: BLE001
            logger.exception("Database close error")
        logger.info("AppContext closed")


def launch_gui(root: Path | None = None) -> int:
    """Create the context, the QApplication and show the main window."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is not installed. Run: pip install PySide6")
        return 2

    from ai_video_factory.ui.widgets.styles import DARK_STYLESHEET

    context = AppContext(root=root)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)

    from ai_video_factory.ui.main_window import MainWindow

    window = MainWindow(context)
    window.show()
    exit_code = app.exec()
    context.close()
    return exit_code
