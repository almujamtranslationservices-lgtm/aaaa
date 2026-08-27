"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_video_factory.config.settings import AppSettings  # noqa: E402
from ai_video_factory.core.event_bus import Event, EventBus  # noqa: E402


class Recorder:
    """Collects events published on a bus (optionally filtered by name)."""

    def __init__(self, bus: EventBus, *names: str) -> None:
        self.events: list[Event] = []
        if names:
            self._unsubscribe = [bus.subscribe(self, event_name=name) for name in names]
        else:
            self._unsubscribe = [bus.subscribe(self)]

    def __call__(self, event: Event) -> None:
        self.events.append(event)

    def of(self, name: str) -> list[Event]:
        return [event for event in self.events if event.name == name]

    def payloads(self, name: str) -> list[dict]:
        return [event.payload for event in self.of(name)]

    def clear(self) -> None:
        self.events.clear()

    def detach(self) -> None:
        for unsub in self._unsubscribe:
            unsub()


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings.defaults(root=tmp_path)
