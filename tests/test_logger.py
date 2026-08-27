"""Tests: logging setup — rotating file, secret redaction, bus feed."""

from __future__ import annotations

import logging

from conftest import Recorder

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.logger import SecretRedactingFilter, setup_logging


def test_secrets_from_env_are_redacted(monkeypatch):
    monkeypatch.setenv("MY_SERVICE_API_KEY", "super-secret-value-123")
    redactor = SecretRedactingFilter()
    cleaned = redactor.redact("calling API with key super-secret-value-123 now")
    assert "super-secret-value-123" not in cleaned
    assert "***REDACTED***" in cleaned


def test_generic_key_patterns_redacted_without_env():
    redactor = SecretRedactingFilter()
    cleaned = redactor.redact("token=sk-AbCdEfGh12345678 failed")
    assert "sk-AbCdEfGh12345678" not in cleaned


def test_setup_logging_writes_redacted_file_and_feeds_bus(tmp_path, monkeypatch):
    # Isolate from other tests (GUI contexts attach handlers to the same logger).
    app_logger = logging.getLogger("ai_video_factory")
    for handler in list(app_logger.handlers):
        app_logger.removeHandler(handler)
        handler.close()

    monkeypatch.setenv("TESTLOG_SECRET_TOKEN", "hide-me-please-999")
    bus = EventBus()
    recorder = Recorder(bus, "log.record")
    logs_dir = tmp_path / "logs"

    root = setup_logging(logs_dir, level="DEBUG", bus=bus)
    logger = logging.getLogger("ai_video_factory.test")
    logger.info("request failed with token hide-me-please-999")
    logger.debug("debug also captured")

    log_text = (logs_dir / "avf.log").read_text(encoding="utf-8")
    assert "hide-me-please-999" not in log_text
    assert "***REDACTED***" in log_text

    events = recorder.of("log.record")
    assert any("hide-me-please-999" not in event.payload["message"] for event in events)
    assert any(event.payload["level"] == "DEBUG" for event in events)
    recorder.detach()

    # Idempotent reconfiguration must not duplicate handlers.
    handlers_before = len(root.handlers)
    setup_logging(logs_dir, level="INFO", bus=bus)
    assert len(root.handlers) == handlers_before
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
