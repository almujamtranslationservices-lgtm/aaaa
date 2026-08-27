"""Thread-safe in-process pub/sub event bus.

The bus is the spine of the application: background workers publish progress,
task and pipeline events; the GUI subscribes and forwards them to Qt signals
(see ``ui/`` in PHASE 3). Handlers run on the *publishing* thread — GUI code
must marshal to the Qt main thread, which the planned ``QtEventBridge``
wrapper will do.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)  # "ai_video_factory.core.event_bus"

Handler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    """An immutable application event."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Publish/subscribe hub safe for use from multiple threads."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str | None, list[Handler]] = {None: []}  # None = all events

    # ---------------------------------------------------------- subscription
    def subscribe(self, handler: Handler, *, event_name: str | None = None) -> Callable[[], None]:
        """Register *handler* for *event_name* (or every event if ``None``).

        Returns an unsubscribe callable.
        """
        with self._lock:
            self._handlers.setdefault(event_name, []).append(handler)

        def _unsubscribe() -> None:
            with self._lock:
                listeners = self._handlers.get(event_name)
                if listeners and handler in listeners:
                    listeners.remove(handler)

        return _unsubscribe

    def unsubscribe(self, handler: Handler, *, event_name: str | None = None) -> None:
        """Explicitly remove a handler (prefer the returned callable)."""
        with self._lock:
            listeners = self._handlers.get(event_name)
            if listeners and handler in listeners:
                listeners.remove(handler)

    # ------------------------------------------------------------- publishing
    def publish(self, event_name: str, **payload: Any) -> Event:
        """Create and emit an event built from keyword arguments.

        Note: the first parameter is ``event_name`` so payloads are free to
        include their own ``name=…`` key.
        """
        return self.emit(Event(name=event_name, payload=payload))

    def emit(self, event: Event) -> Event:
        """Deliver *event* to all matching handlers (isolated failures)."""
        with self._lock:
            handlers = list(self._handlers.get(None, [])) + list(self._handlers.get(event.name, []))
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 — a bad listener must never kill the publisher
                # Logged, not re-raised. logger name is skipped by the UI log
                # handler to avoid infinite recursion.
                logger.warning("Event handler %r failed for '%s': %s", handler, event.name, exc)
        return event

    # --------------------------------------------------------------- helpers
    def handler_count(self, event_name: str | None = None) -> int:
        with self._lock:
            return len(self._handlers.get(event_name, []))
