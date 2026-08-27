"""Tests: TaskManager — success, progress, retry, failure, cancel, persistence."""

from __future__ import annotations

import time
from typing import Any

import pytest

from conftest import Recorder

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.task_manager import TaskManager, TaskStatus


class FakePersistence:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def upsert_task(self, task: dict[str, Any]) -> None:
        self.saved.append({key: value for key, value in task.items() if key != "metadata"})


@pytest.fixture()
def persistence() -> FakePersistence:
    return FakePersistence()


@pytest.fixture()
def manager(bus: EventBus, persistence: FakePersistence) -> TaskManager:
    return TaskManager(bus, max_workers=2, persistence=persistence, retry_base_delay=0.05)


def _wait_terminal(manager: TaskManager, task_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.get(task_id).status  # type: ignore[union-attr]
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return
        time.sleep(0.02)
    raise AssertionError("Task did not reach a terminal status in time")


def test_successful_task_reports_progress_and_persists(bus, manager, persistence):
    recorder = Recorder(bus, "task.progress", "task.succeeded")
    seen: dict[str, Any] = {}

    def work(ctx) -> str:
        seen["cancelled_flag"] = ctx.is_cancelled()
        for index in range(4):
            ctx.report_progress((index + 1) / 4, f"step {index}")
        return "done!"

    task = manager.submit("demo", work)
    _wait_terminal(manager, task.id)
    assert task.status == TaskStatus.COMPLETED
    assert task.result == "done!"
    assert task.attempts == 1
    assert seen["cancelled_flag"] is False
    progress = recorder.payloads("task.progress")
    assert progress[-1]["progress"] == 1.0
    assert recorder.of("task.succeeded")
    # persistence: queued + started (+ progress none) + completed
    statuses = [entry["status"] for entry in persistence.saved]
    assert "completed" in statuses and "running" in statuses
    recorder.detach()


def test_retry_then_success(bus, manager):
    recorder = Recorder(bus, "task.retry")
    attempts = {"count": 0}

    def flaky(ctx) -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("transient failure")
        return "recovered"

    task = manager.submit("flaky", flaky, max_retries=3)
    _wait_terminal(manager, task.id)
    assert task.status == TaskStatus.COMPLETED
    assert attempts["count"] == 3
    assert len(recorder.of("task.retry")) == 2
    recorder.detach()


def test_failure_after_exhausted_retries(bus, manager):
    recorder = Recorder(bus, "task.failed")

    def always_fails(ctx) -> None:
        raise RuntimeError("permanent")

    task = manager.submit("bad", always_fails, max_retries=1)
    _wait_terminal(manager, task.id)
    assert task.status == TaskStatus.FAILED
    assert task.attempts == 2
    assert "RuntimeError: permanent" in task.error
    assert recorder.of("task.failed")
    recorder.detach()


def test_cooperative_cancellation(bus, manager):
    recorder = Recorder(bus, "task.cancelled")

    def long_task(ctx) -> None:
        for _ in range(200):
            ctx.check_cancelled()
            time.sleep(0.01)

    task = manager.submit("long", long_task)
    time.sleep(0.05)
    assert manager.cancel(task.id) is True
    _wait_terminal(manager, task.id)
    assert task.status == TaskStatus.CANCELLED
    assert recorder.of("task.cancelled")
    recorder.detach()


def test_cancel_before_start(bus):
    manager = TaskManager(bus, max_workers=1)
    blocker = manager.submit("blocker", lambda ctx: time.sleep(0.2))
    queued = manager.submit("queued", lambda ctx: "never runs")
    manager.cancel(queued.id)
    _wait_terminal(manager, blocker.id)
    _wait_terminal(manager, queued.id)
    assert queued.status == TaskStatus.CANCELLED
    assert blocker.status == TaskStatus.COMPLETED
    manager.shutdown()


def test_retry_failed_task_manually(bus, manager):
    attempts = {"count": 0}

    def fail_once(ctx) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("first time fails")
        return "ok"

    task = manager.submit("manual-retry", fail_once, max_retries=0)
    _wait_terminal(manager, task.id)
    assert task.status == TaskStatus.FAILED
    retried = manager.retry(task.id)
    assert retried is not None
    _wait_terminal(manager, task.id)
    assert task.status == TaskStatus.COMPLETED
    assert attempts["count"] == 2


def test_stats_and_shutdown(bus, manager):
    task = manager.submit("quick", lambda ctx: 42)
    _wait_terminal(manager, task.id)
    stats = manager.stats()
    assert stats["completed"] == 1
    manager.shutdown()
    with pytest.raises(RuntimeError):
        manager.submit("after-shutdown", lambda ctx: None)


def test_task_to_dict_json_safe(bus):
    manager = TaskManager(bus)
    task = manager.submit("dict-check", lambda ctx: object())
    _wait_terminal(manager, task.id)
    data = task.to_dict()
    import json

    json.dumps(data)  # must not raise
    assert data["status"] == "completed"
    manager.shutdown()
