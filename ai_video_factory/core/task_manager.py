"""Background task queue with retry, cancellation and persistence hooks.

The manager keeps the UI responsive: heavy work (provider calls, rendering)
runs in a thread pool while progress flows through the event bus as
``task.queued`` / ``task.started`` / ``task.progress`` / ``task.stage`` /
``task.retry`` / ``task.succeeded`` / ``task.failed`` / ``task.cancelled``.

Tasks cooperate with cancellation: long-running callables receive a
:class:`TaskContext` and should check ``ctx.is_cancelled()`` (or call
``ctx.check_cancelled()``) inside their loops.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.exceptions import TaskCancelledError

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class TaskPersistence(Protocol):
    """Minimal storage contract (implemented by ``database.repositories.TaskRepository``)."""

    def upsert_task(self, task: dict[str, Any]) -> None: ...


@dataclass
class Task:
    """A unit of background work."""

    id: str
    name: str
    fn: Callable[["TaskContext"], Any]
    max_retries: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)

    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    error: str | None = None
    result: Any = None
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    @property
    def max_attempts(self) -> int:
        return 1 + max(0, self.max_retries)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe projection for persistence / the UI."""

        def _iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        result: Any = self.result
        if result is not None and not isinstance(result, (str, int, float, bool, dict, list)):
            result = str(result)[:500]
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "error": self.error,
            "result": result,
            "metadata": dict(self.metadata),
            "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
        }


class TaskContext:
    """Passed to every task callable — progress reporting and cancellation."""

    def __init__(self, task: Task, bus: EventBus) -> None:
        self._task = task
        self._bus = bus

    @property
    def task_id(self) -> str:
        return self._task.id

    @property
    def task_name(self) -> str:
        return self._task.name

    @property
    def metadata(self) -> dict[str, Any]:
        return self._task.metadata

    @property
    def cancel_event(self) -> threading.Event:
        return self._task.cancel_event

    def is_cancelled(self) -> bool:
        return self._task.cancel_event.is_set()

    def check_cancelled(self) -> None:
        """Raise :class:`TaskCancelledError` if cancellation was requested."""
        if self.is_cancelled():
            raise TaskCancelledError(f"Task '{self._task.name}' ({self._task.id}) was cancelled")

    def report_progress(self, fraction: float, message: str = "") -> None:
        """Report progress in the ``0.0 … 1.0`` range."""
        fraction = min(1.0, max(0.0, fraction))
        self._bus.publish(
            "task.progress", task_id=self._task.id, name=self._task.name,
            progress=fraction, message=message,
        )

    def report_stage(self, stage: str, **extra: Any) -> None:
        """Report the current human-readable step (e.g. 'Scene 12/40 — image')."""
        self._bus.publish("task.stage", task_id=self._task.id, name=self._task.name, stage=stage, **extra)


class TaskManager:
    """Runs tasks in a bounded thread pool with retry and persistence."""

    def __init__(
        self,
        bus: EventBus,
        *,
        max_workers: int = 4,
        persistence: TaskPersistence | None = None,
        retry_base_delay: float = 0.5,
    ) -> None:
        self._bus = bus
        self._persistence = persistence
        self._retry_base_delay = retry_base_delay
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="avf-task"
        )
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()
        self._shutdown = False

    # -------------------------------------------------------------- submission
    def submit(
        self,
        name: str,
        fn: Callable[[TaskContext], Any],
        *,
        max_retries: int = 2,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> Task:
        """Queue *fn* for background execution and return its :class:`Task`."""
        if self._shutdown:
            raise RuntimeError("TaskManager is shut down")
        task = Task(
            id=task_id or uuid.uuid4().hex[:12],
            name=name,
            fn=fn,
            max_retries=max_retries,
            metadata=metadata or {},
        )
        with self._lock:
            self._tasks[task.id] = task
        self._persist(task)
        self._bus.publish("task.queued", task_id=task.id, name=task.name)
        self._executor.submit(self._run, task)
        return task

    # ------------------------------------------------------------------ worker
    def _run(self, task: Task) -> None:
        if task.cancel_event.is_set():
            self._finish(task, TaskStatus.CANCELLED, error="cancelled before start")
            self._bus.publish("task.cancelled", task_id=task.id, name=task.name)
            return

        task.started_at = utcnow()
        while True:
            task.attempts += 1
            task.status = TaskStatus.RUNNING
            task.error = None
            self._persist(task)
            self._bus.publish(
                "task.started", task_id=task.id, name=task.name,
                attempt=task.attempts, max_attempts=task.max_attempts,
            )
            try:
                task.result = task.fn(TaskContext(task, self._bus))
            except (TaskCancelledError, concurrent.futures.CancelledError) as exc:
                self._finish(task, TaskStatus.CANCELLED, error=str(exc) or "cancelled")
                self._bus.publish("task.cancelled", task_id=task.id, name=task.name)
                return
            except Exception as exc:  # noqa: BLE001 — worker boundary
                task.error = f"{type(exc).__name__}: {exc}"
                logger.exception("Task '%s' (%s) failed on attempt %d/%d",
                                 task.name, task.id, task.attempts, task.max_attempts)
                if self._can_retry(task):
                    task.status = TaskStatus.RETRYING
                    self._persist(task)
                    self._bus.publish(
                        "task.retry", task_id=task.id, name=task.name,
                        attempt=task.attempts, max_attempts=task.max_attempts, error=task.error,
                    )
                    if task.cancel_event.wait(timeout=self._retry_base_delay * task.attempts):
                        self._finish(task, TaskStatus.CANCELLED, error="cancelled during retry")
                        self._bus.publish("task.cancelled", task_id=task.id, name=task.name)
                        return
                    continue
                self._finish(task, TaskStatus.FAILED)
                self._bus.publish("task.failed", task_id=task.id, name=task.name,
                                  attempt=task.attempts, error=task.error)
                return
            else:
                self._finish(task, TaskStatus.COMPLETED)
                preview = task.result if isinstance(task.result, str) else None
                self._bus.publish("task.succeeded", task_id=task.id, name=task.name,
                                  result=preview[:200] if preview else None)
                return

    def _can_retry(self, task: Task) -> bool:
        return (
            task.attempts < task.max_attempts
            and not task.cancel_event.is_set()
            and not self._shutdown
        )

    def _finish(self, task: Task, status: TaskStatus, *, error: str | None = None) -> None:
        task.status = status
        task.finished_at = utcnow()
        if error:
            task.error = error
        self._persist(task)

    def _persist(self, task: Task) -> None:
        if self._persistence is None:
            return
        try:
            self._persistence.upsert_task(task.to_dict())
        except Exception:  # noqa: BLE001 — persistence must not break execution
            logger.exception("Failed to persist task %s", task.id)

    # ------------------------------------------------------------- control API
    def cancel(self, task_id: str) -> bool:
        """Request cooperative cancellation. Returns ``True`` if the task exists."""
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return False
        task.cancel_event.set()
        if task.status in (TaskStatus.PENDING, TaskStatus.RETRYING, TaskStatus.FAILED):
            task.status = TaskStatus.CANCELLED
            task.finished_at = utcnow()
            self._persist(task)
        self._bus.publish("task.cancel_requested", task_id=task.id, name=task.name)
        return True

    def retry(self, task_id: str) -> Task | None:
        """Re-queue a terminal (failed/cancelled) task. Returns it, or ``None``."""
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None or task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            return None
        task.error = None
        task.finished_at = None
        task.cancel_event.clear()
        task.status = TaskStatus.PENDING
        self._persist(task)
        self._bus.publish("task.queued", task_id=task.id, name=task.name, retried=True)
        self._executor.submit(self._run, task)
        return task

    # ------------------------------------------------------------------ queries
    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def tasks(self) -> list[Task]:
        with self._lock:
            return sorted(self._tasks.values(), key=lambda t: t.created_at)

    def stats(self) -> dict[str, int]:
        counts: dict[str, int] = {status.value: 0 for status in TaskStatus}
        with self._lock:
            for task in self._tasks.values():
                counts[task.status.value] += 1
        return counts

    # ---------------------------------------------------------------- shutdown
    def shutdown(self, *, wait: bool = True) -> None:
        """Stop accepting work and (optionally) wait for running tasks."""
        self._shutdown = True
        self._executor.shutdown(wait=wait)
