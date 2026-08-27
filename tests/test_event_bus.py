"""Tests: event bus behaviour (thread-safety, isolation, wildcards)."""

from __future__ import annotations

import threading

from ai_video_factory.core.event_bus import Event, EventBus


def test_publish_reaches_named_and_wildcard_handlers():
    bus = EventBus()
    named_events, all_events = [], []
    bus.subscribe(lambda e: named_events.append(e), event_name="task.started")
    bus.subscribe(lambda e: all_events.append(e))
    bus.publish("task.started", task_id="t1")
    bus.publish("task.failed", task_id="t2")
    assert len(named_events) == 1
    assert len(all_events) == 2


def test_unsubscribe_token():
    bus = EventBus()
    seen = []
    unsubscribe = bus.subscribe(lambda e: seen.append(e), event_name="x")
    unsubscribe()
    bus.publish("x")
    assert seen == []
    assert bus.handler_count("x") == 0


def test_handler_exception_does_not_break_other_handlers():
    bus = EventBus()
    received = []

    def broken(_event: Event) -> None:
        raise RuntimeError("boom")

    bus.subscribe(broken, event_name="x")
    bus.subscribe(lambda e: received.append(e), event_name="x")
    event = bus.publish("x", value=1)
    assert received == [event]


def test_events_are_isolated_snapshots():
    bus = EventBus()
    first, second = [], []
    bus.subscribe(lambda e: first.append(e), event_name="x")
    unsubscribe = bus.subscribe(lambda e: second.append(e), event_name="x")
    unsubscribe()
    bus.publish("x")
    assert len(first) == 1 and len(second) == 0


def test_multithreaded_publish_subscribe():
    bus = EventBus()
    collected: list[Event] = []
    lock = threading.Lock()

    def handler(event: Event) -> None:
        with lock:
            collected.append(event)

    bus.subscribe(handler)

    def publish_many(index: int) -> None:
        bus.publish(f"evt.{index}", value=index)

    threads = [threading.Thread(target=publish_many, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(collected) == 20
