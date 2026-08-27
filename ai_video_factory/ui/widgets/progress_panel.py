"""Real progress panel: current task, current stage/scene, elapsed, ETA, errors.

Subscribes to every ``task.*`` and ``pipeline.*`` event through the Qt event
bridge — the same events the (future) rendering pipeline emits with weighted
percentages (Script 10% → Scenes 20% → Images 40% → … → 100%).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QProgressBar, QVBoxLayout,
)

from ai_video_factory.core.event_bus import Event, EventBus
from ai_video_factory.core.task_manager import TaskManager
from ai_video_factory.ui.widgets.event_bridge import on_event
from ai_video_factory.utils.time_utils import estimate_eta, format_duration, format_eta


class ProgressPanel(QFrame):
    """Live progress display for tasks and pipelines."""

    def __init__(self, task_manager: TaskManager, bus: EventBus,
                 parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProgressPanel")
        self._bus = bus
        self._running: dict[str, dict] = {}
        self._pipeline_started_at: float | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        header = QHBoxLayout()
        self._title = QLabel("Progress")
        self._title.setObjectName("CardTitle")
        self._elapsed = QLabel("00:00")
        self._eta = QLabel("ETA —")
        for widget in (self._elapsed, self._eta):
            widget.setObjectName("MutedLabel")
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(QLabel("⏱"))
        header.addWidget(self._elapsed)
        header.addWidget(QLabel("·"))
        header.addWidget(self._eta)
        root.addLayout(header)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        root.addWidget(self._bar)

        meta = QHBoxLayout()
        self._task_label = QLabel("Idle — no active tasks")
        self._task_label.setObjectName("MutedLabel")
        self._stage_label = QLabel("")
        self._stage_label.setObjectName("MutedLabel")
        meta.addWidget(self._task_label, 3)
        meta.addWidget(self._stage_label, 2)
        root.addLayout(meta)

        self._errors = QListWidget()
        self._errors.setMaximumHeight(96)
        self._errors.setHidden(True)
        self._errors.setAlternatingRowColors(True)
        root.addWidget(self._errors)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self._connect_events()

    # ------------------------------------------------------------------ wiring
    def _connect_events(self) -> None:
        bindings = {
            "task.started": self._on_task_started,
            "task.progress": self._on_task_progress,
            "task.stage": self._on_task_stage,
            "task.retry": self._on_task_retry,
            "task.succeeded": self._on_task_terminal,
            "task.failed": self._on_task_failed,
            "task.cancelled": self._on_task_terminal,
            "pipeline.started": self._on_pipeline_started,
            "pipeline.progress": self._on_pipeline_progress,
            "pipeline.completed": self._on_pipeline_done,
            "pipeline.cancelled": self._on_pipeline_done,
            "pipeline.failed": self._on_pipeline_failed,
        }
        for name, slot in bindings.items():
            on_event(self, self._bus, name, slot)

    # ------------------------------------------------------------- task events
    def _on_task_started(self, event: Event) -> None:
        payload = event.payload
        self._running[payload["task_id"]] = {
            "name": payload.get("name", ""),
            "start": time.monotonic(),
        }
        self._task_label.setText(f"⚙ {payload.get('name', '')} "
                                  f"(attempt {payload.get('attempt', 1)}/{payload.get('max_attempts', 1)})")
        if not self._timer.isActive():
            self._timer.start()
            self._elapsed.setText("00:00")

    def _on_task_progress(self, event: Event) -> None:
        if self._pipeline_started_at is None:  # standalone task → show its own progress
            self._bar.setValue(int(event.payload.get("progress", 0.0) * 100))
        message = event.payload.get("message") or ""
        if message:
            self._stage_label.setText(message)

    def _on_task_stage(self, event: Event) -> None:
        self._stage_label.setText(str(event.payload.get("stage", "")))

    def _on_task_retry(self, event: Event) -> None:
        payload = event.payload
        self._add_error(f"↻ retry {payload.get('name')} "
                        f"({payload.get('attempt')}/{payload.get('max_attempts')}): {payload.get('error', '')}")

    def _on_task_failed(self, event: Event) -> None:
        payload = event.payload
        self._add_error(f"✖ {payload.get('name', '')}: {payload.get('error', '')}")
        self._finish_task(payload)

    def _on_task_terminal(self, event: Event) -> None:
        self._finish_task(event.payload)

    def _finish_task(self, payload: dict) -> None:
        self._running.pop(payload.get("task_id", ""), None)
        if not self._running:
            self._timer.stop()
            self._task_label.setText("Idle — no active tasks")
            self._stage_label.setText("")

    # --------------------------------------------------------- pipeline events
    def _on_pipeline_started(self, event: Event) -> None:
        self._pipeline_started_at = time.monotonic()
        self._bar.setValue(0)
        self._errors.clear()
        self._errors.setHidden(True)
        self._title.setText(f"Pipeline — {event.payload.get('project_name', '')}")
        self._timer.start()

    def _on_pipeline_progress(self, event: Event) -> None:
        percent = float(event.payload.get("percent", 0.0))
        self._bar.setValue(int(percent))
        stage = event.payload.get("stage", "")
        message = event.payload.get("message", "")
        self._stage_label.setText(f"{stage} — {message}".strip(" —"))
        if self._pipeline_started_at is not None:
            eta = estimate_eta(time.monotonic() - self._pipeline_started_at, percent / 100.0)
            self._eta.setText(f"ETA {format_eta(eta)}")

    def _on_pipeline_done(self, event: Event) -> None:
        self._pipeline_started_at = None
        self._bar.setValue(100)
        self._title.setText("Pipeline — completed ✓")
        self._task_label.setText("Idle — no active tasks")
        if not self._running:
            self._timer.stop()

    def _on_pipeline_failed(self, event: Event) -> None:
        self._pipeline_started_at = None
        self._add_error(f"✖ pipeline stage '{event.payload.get('stage')}': {event.payload.get('error', '')}")
        self._title.setText("Pipeline — failed")
        if not self._running:
            self._timer.stop()

    # --------------------------------------------------------------- internals
    def _tick(self) -> None:
        starts = [task["start"] for task in self._running.values()]
        if self._pipeline_started_at is not None:
            starts.append(self._pipeline_started_at)
        if starts:
            self._elapsed.setText(format_duration(time.monotonic() - min(starts)))

    def _add_error(self, text: str) -> None:
        self._errors.setHidden(False)
        self._errors.insertItem(0, text)
        while self._errors.count() > 50:
            self._errors.takeItem(self._errors.count() - 1)

    def reset(self) -> None:
        self._bar.setValue(0)
        self._errors.clear()
        self._errors.setHidden(True)
        self._task_label.setText("Idle — no active tasks")
        self._stage_label.setText("")
        self._eta.setText("ETA —")
        self._elapsed.setText("00:00")
        self._pipeline_started_at = None
        self._timer.stop()
