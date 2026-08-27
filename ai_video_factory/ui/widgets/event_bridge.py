"""Thread-safe bridge from the asyncio/thread-pool world to Qt signals.

Background workers publish events on :class:`EventBus` from their own
threads. :class:`EventBridge` re-emits them as a Qt signal; because the
bridge object lives in the GUI thread, Qt automatically uses a *queued*
connection, so every slot runs safely on the main thread — the UI never
blocks and never touches widgets from worker threads.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from ai_video_factory.core.event_bus import Event, EventBus


class EventBridge(QObject):
    """Forwards every bus event to the ``event_received`` Qt signal."""

    event_received = Signal(object)

    def __init__(self, bus: EventBus, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._unsubscribe = bus.subscribe(self._forward)

    def _forward(self, event: Event) -> None:
        try:
            self.event_received.emit(event)
        except RuntimeError:
            # The C++ side was destroyed — stop listening.
            self._unsubscribe()

    def close(self) -> None:
        self._unsubscribe()


def on_event(owner: QObject, bus: EventBus, event_name: str,
             slot: Callable[[Event], None]) -> EventBridge:
    """Subscribe *owner* to one event type; the bridge is parented to *owner*.

    The returned bridge is also stored on the owner (``_bridge_<name>``) to
    prevent garbage collection. Cross-thread deliveries are queued by Qt.
    """
    bridge = EventBridge(bus, parent=owner)

    def dispatch(event: Any) -> None:
        if event.name == event_name:
            slot(event)

    bridge.event_received.connect(dispatch)
    setattr(owner, f"_bridge_{event_name.replace('.', '_')}", bridge)
    return bridge
