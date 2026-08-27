"""Logging setup: rotating file + console + event-bus feed, with secret redaction.

Security rules enforced here
----------------------------
* Values of environment variables whose name contains ``KEY`` / ``TOKEN`` /
  ``SECRET`` / ``PASSWORD`` are replaced with ``***REDACTED***`` in every
  log record.
* Common API-key patterns (``sk-…``, ``AIza…``) are masked even if they came
  from somewhere other than the environment.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
from pathlib import Path

from ai_video_factory.core.event_bus import Event, EventBus

LOGGER_NAME = "ai_video_factory"

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Name whose records never reach the bus (prevents publish → log → publish loops).
_BUS_SKIPPED_LOGGER = "ai_video_factory.core.event_bus"

_SECRET_KEY_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_GENERIC_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{15,}", re.IGNORECASE),
)


class SecretRedactingFilter(logging.Filter):
    """Redact secret values from every record that passes through."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets = self._collect_env_secrets()

    @staticmethod
    def _collect_env_secrets() -> list[str]:
        secrets: list[str] = []
        for name, value in os.environ.items():
            if any(marker in name.upper() for marker in _SECRET_KEY_MARKERS) and value and len(value) >= 6:
                secrets.append(value)
        return sorted(set(secrets), key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            if secret and secret in text:
                text = text.replace(secret, "***REDACTED***")
        for pattern in _GENERIC_SECRET_PATTERNS:
            text = pattern.sub("***REDACTED***", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self.redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


class EventBusHandler(logging.Handler):
    """Forward log records to the UI Logs view through the event bus."""

    def __init__(self, bus: EventBus, redactor: SecretRedactingFilter, min_level: int = logging.INFO) -> None:
        super().__init__(level=min_level)
        self._bus = bus
        self._redactor = redactor

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == _BUS_SKIPPED_LOGGER:
            return
        try:
            message = self._redactor.redact(self.format(record))
        except Exception:  # pragma: no cover — never crash on formatting
            message = record.getMessage()
        self._bus.emit(Event(
            name="log.record",
            payload={
                "level": record.levelname,
                "logger": record.name,
                "message": message,
                "timestamp": record.created,
            },
        ))


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger of the application logger."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def setup_logging(
    logs_dir: Path,
    *,
    level: str | int = logging.INFO,
    bus: EventBus | None = None,
) -> logging.Logger:
    """Initialise (idempotently) the application logging tree.

    Args:
        logs_dir: directory for the rotating ``avf.log`` file.
        level: root level name or numeric value.
        bus: optional event bus receiving log records for the UI.

    Returns:
        The configured application logger.
    """
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(level)
    if root.handlers:  # already configured — just honour the new level
        return root

    logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    redactor = SecretRedactingFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "avf.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redactor)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    if bus is not None:
        bus_handler = EventBusHandler(bus, redactor, min_level=level)
        bus_handler.setFormatter(formatter)
        root.addHandler(bus_handler)

    root.debug("Logging initialised (level=%s, dir=%s)", logging.getLevelName(level), logs_dir)
    return root
