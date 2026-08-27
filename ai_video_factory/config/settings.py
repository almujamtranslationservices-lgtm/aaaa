"""Application settings: defaults, JSON persistence and .env overrides.

Design notes
------------
* Settings contain **no secrets** — API keys live only in ``.env`` and are
  read directly by providers at call time.
* Layered loading (lowest → highest priority):
  1. Built-in defaults (relative to the repository root).
  2. ``config/settings.json`` (created by the app / user preferences).
  3. Environment variables (``.env`` is loaded via python-dotenv).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

APP_NAME = "AI Video Factory"
APP_ID = "ai_video_factory"


def project_root() -> Path:
    """Return the project root directory (two levels above this file)."""
    return Path(__file__).resolve().parent.parent.parent


class ProviderSelection(BaseModel):
    """Currently selected provider id per capability (free-first defaults)."""

    llm: str = "demo"
    image: str = "demo"
    video: str = "demo"
    voice: str = "demo"


class AppSettings(BaseModel):
    """User-facing application settings (validated with pydantic)."""

    # Behaviour
    demo_mode: bool = True
    language: str = "ar"
    theme: str = "dark"
    log_level: str = "INFO"

    # Autosave / tasks
    autosave_enabled: bool = True
    autosave_interval_seconds: float = Field(default=30.0, gt=0)
    max_parallel_tasks: int = Field(default=4, ge=1, le=32)
    retry_max_attempts: int = Field(default=3, ge=1, le=10)
    request_timeout_seconds: float = Field(default=120.0, gt=0)

    # Paths
    projects_dir: Path
    output_dir: Path
    assets_dir: Path
    logs_dir: Path
    database_path: Path

    # Provider selection
    providers: ProviderSelection = Field(default_factory=ProviderSelection)

    def ensure_directories(self) -> None:
        """Create every managed directory if it does not exist yet."""
        for path in (self.projects_dir, self.output_dir, self.assets_dir, self.logs_dir, self.database_path.parent):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def defaults(cls, root: Path | None = None) -> "AppSettings":
        """Build the default settings anchored at *root* (default: repo root)."""
        root = (root or project_root()).resolve()
        return cls(
            projects_dir=root / "projects",
            output_dir=root / "output",
            assets_dir=root / "assets",
            logs_dir=root / "logs",
            database_path=root / "data" / "avf.sqlite3",
        )


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Environment overrides applied on top of the settings file.
_ENV_OVERRIDES: dict[str, tuple[str, Any]] = {
    "AVF_DEMO_MODE": ("demo_mode", _to_bool),
    "AVF_LANGUAGE": ("language", str),
    "AVF_LOG_LEVEL": ("log_level", str),
    "AVF_THEME": ("theme", str),
    "AVF_PROJECTS_DIR": ("projects_dir", Path),
    "AVF_OUTPUT_DIR": ("output_dir", Path),
    "AVF_LOGS_DIR": ("logs_dir", Path),
    "AVF_MAX_PARALLEL_TASKS": ("max_parallel_tasks", int),
}


class SettingsService:
    """Load / save / observe :class:`AppSettings`."""

    def __init__(
        self,
        *,
        config_file: Path | None = None,
        env_file: Path | None = None,
        root: Path | None = None,
    ) -> None:
        self.root = (root or project_root()).resolve()
        self._config_file = config_file or self.root / "config" / "settings.json"
        if env_file is not None:
            load_dotenv(env_file, override=False)
        else:
            load_dotenv(self.root / ".env", override=False)
        self._settings = self._load()
        self._settings.ensure_directories()

    # ------------------------------------------------------------------ load
    def _load(self) -> AppSettings:
        merged: dict[str, Any] = AppSettings.defaults(self.root).model_dump()

        if self._config_file.exists():
            try:
                merged.update(json.loads(self._config_file.read_text(encoding="utf-8")))
                logger.debug("Loaded settings from %s", self._config_file)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Ignoring corrupted settings file %s: %s", self._config_file, exc)

        env_overrides = {
            field: cast(os.environ[env_var])
            for env_var, (field, cast) in _ENV_OVERRIDES.items()
            if os.environ.get(env_var)
        }
        if env_overrides:
            logger.debug("Applying env overrides: %s", sorted(env_overrides))
            merged.update(env_overrides)

        return AppSettings.model_validate(merged)

    # ----------------------------------------------------------------- access
    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def config_file(self) -> Path:
        return self._config_file

    def update(self, **changes: Any) -> AppSettings:
        """Validate and apply *changes*, then persist them to the JSON file."""
        merged = self._settings.model_dump()
        merged.update(changes)
        self._settings = AppSettings.model_validate(merged)
        self.save()
        return self._settings

    # ---------------------------------------------------------------- persist
    def save(self) -> None:
        payload = self._settings.model_dump(mode="json")
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._config_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._config_file)
        logger.debug("Saved settings to %s", self._config_file)
