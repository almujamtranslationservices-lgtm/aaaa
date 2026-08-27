"""Logs page — live, coloured log stream fed by the event bus (spec §23)."""

from __future__ import annotations

import html
import time

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ai_video_factory.core.event_bus import Event, EventBus
from ai_video_factory.ui.widgets.event_bridge import on_event

_LEVEL_COLORS = {
    "DEBUG": "#8a919e",
    "INFO": "#9ecbff",
    "WARNING": "#ffcf6b",
    "ERROR": "#ff7b72",
    "CRITICAL": "#ff5252",
}
_LEVEL_ORDER = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LogsPage(QWidget):
    """Read-only live log viewer with level filter and autoscroll."""

    def __init__(self, bus: EventBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = bus

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Logs")
        title.setObjectName("SectionTitle")
        subtitle = QLabel("API keys are automatically redacted (core/logger.py).")
        subtitle.setObjectName("MutedLabel")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(subtitle)
        root.addLayout(header)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Minimum level:"))
        self._filter = QComboBox()
        for level in _LEVEL_ORDER:
            self._filter.addItem(level)
        self._filter.setCurrentText("INFO")
        self._autoscroll = QCheckBox("Auto-scroll")
        self._autoscroll.setChecked(True)
        clear_button = QPushButton("🗑  Clear")
        clear_button.clicked.connect(lambda: self._view.clear())
        controls.addWidget(self._filter)
        controls.addWidget(self._autoscroll)
        controls.addStretch(1)
        controls.addWidget(clear_button)
        root.addLayout(controls)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(3000)
        self._view.setFont(QFont("Monospace", 10))
        self._view.setStyleSheet("QPlainTextEdit { font-family: 'DejaVu Sans Mono', Consolas, monospace; }")
        root.addWidget(self._view, 1)

        on_event(self, self._bus, "log.record", self._on_log)

    def _on_log(self, event: Event) -> None:
        payload = event.payload
        level = str(payload.get("level", "INFO"))
        level_index = _LEVEL_ORDER.index(level) if level in _LEVEL_ORDER else 1
        minimum_index = _LEVEL_ORDER.index(self._filter.currentText()) if self._filter.currentText() in _LEVEL_ORDER else 1
        if level_index < minimum_index:
            return
        timestamp = time.strftime("%H:%M:%S", time.localtime(float(payload.get("timestamp", time.time()))))
        color = _LEVEL_COLORS.get(level, "#e8eaf2")
        logger = html.escape(str(payload.get("logger", "")))
        message = html.escape(str(payload.get("message", "")))
        self._view.appendHtml(
            f'<span style="color:#5a6272">{timestamp}</span> '
            f'<span style="color:{color}"><b>{level:<8}</b></span> '
            f'<span style="color:#8a93a5">{logger}</span> '
            f'<span>{message}</span>'
        )
        if self._autoscroll.isChecked():
            scrollbar = self._view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
