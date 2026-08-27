"""Tests: pipeline orchestration — weights, progress, skip, failure, cancel."""

from __future__ import annotations

import pytest

from conftest import Recorder

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.exceptions import StageSkipRequested
from ai_video_factory.core.pipeline import Pipeline, PipelineContext, PipelineStage
from ai_video_factory.models.project import Project


class RecordingStage(PipelineStage):
    def __init__(self, name: str, weight: float = 1.0, *, fails: bool = False,
                 on_error: str = "abort", sleep: float = 0.0) -> None:
        self.name = name
        self.weight = weight
        self.on_error = on_error  # type: ignore[assignment]
        self._fails = fails
        self._sleep = sleep
        self.calls = 0

    def run(self, ctx: PipelineContext) -> None:
        self.calls += 1
        ctx.set(f"{self.name}.called", True)
        if self._sleep:
            import time

            time.sleep(self._sleep)
        if self._fails:
            raise RuntimeError(f"{self.name} exploded")


@pytest.fixture()
def project() -> Project:
    return Project(name="Pipeline Test", idea="idea", target_duration=30)


@pytest.fixture()
def ctx(project, tmp_path) -> PipelineContext:
    return PipelineContext(project=project, workdir=tmp_path)


def test_stages_run_in_order_and_publish_weighted_progress(bus, ctx):
    recorder = Recorder(bus, "pipeline.progress", "pipeline.stage.completed", "pipeline.completed")
    pipeline = Pipeline([RecordingStage("a", weight=7.0), RecordingStage("b", weight=3.0)], bus=bus)
    result = pipeline.run(ctx)

    assert result.success is True
    assert [r.name for r in result.stage_results] == ["a", "b"]
    percents = [event.payload["percent"] for event in recorder.of("pipeline.progress")]
    assert percents[-1] == 100.0
    assert percents[0] == pytest.approx(70.0)  # a = 7/10
    assert ctx.get("a.called") and ctx.get("b.called")
    completed = recorder.of("pipeline.completed")
    assert completed[0].payload["success"] is True
    recorder.detach()


def test_stage_internal_progress_reports_through_hook(bus, ctx):
    recorder = Recorder(bus, "pipeline.progress")
    engine_holder = {}

    class SlowStage(PipelineStage):
        name = "slow"
        weight = 10.0

        def run(self, context: PipelineContext) -> None:
            context.report_progress(0.5, "halfway")

    pipeline = Pipeline([SlowStage()], bus=bus)
    pipeline.run(ctx)
    halfway = [e for e in recorder.of("pipeline.progress") if e.payload.get("message") == "halfway"]
    assert halfway[0].payload["percent"] == pytest.approx(50.0)
    recorder.detach()


def test_failure_aborts_pipeline(bus, ctx):
    recorder = Recorder(bus, "pipeline.failed")
    failing = RecordingStage("boom", fails=True)
    after = RecordingStage("after")
    result = Pipeline([failing, after], bus=bus).run(ctx)

    assert result.success is False
    assert result.error and "boom" in result.error
    assert after.calls == 0
    assert recorder.of("pipeline.failed")
    recorder.detach()


def test_on_error_skip_continues(bus, ctx):
    failing = RecordingStage("boom", fails=True, on_error="skip")
    after = RecordingStage("after")
    result = Pipeline([failing, after], bus=bus).run(ctx)
    assert result.success is True
    outcomes = {r.name: r.outcome for r in result.stage_results}
    assert outcomes == {"boom": "skipped", "after": "ok"}
    assert "exploded" in result.stage_results[0].error  # error preserved on the skipped stage


def test_retry_policy_on_stage(bus, ctx):
    class FlakyStage(PipelineStage):
        name = "flaky"
        weight = 1.0
        on_error = "retry"
        max_retries = 2
        attempts = 0

        def run(self, context: PipelineContext) -> None:
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise RuntimeError("transient")

    result = Pipeline([FlakyStage()], bus=bus).run(ctx)
    assert result.success is True
    assert FlakyStage.attempts == 2


def test_should_skip_uses_cache(bus, ctx):
    recorder = Recorder(bus, "pipeline.progress")

    class CachedStage(PipelineStage):
        name = "cached"
        weight = 5.0
        calls = 0

        def should_skip(self, context: PipelineContext) -> bool:
            return True

        def run(self, context: PipelineContext) -> None:
            type(self).calls += 1

    fresh = RecordingStage("fresh", weight=5.0)
    result = Pipeline([CachedStage(), fresh], bus=bus).run(ctx)
    assert result.success is True
    assert result.stage_results[0].outcome == "skipped"
    assert CachedStage.calls == 0 and fresh.calls == 1
    recorder.detach()


def test_stage_can_request_skip_via_exception(bus, ctx):
    class SkippingStage(PipelineStage):
        name = "skipper"

        def run(self, context: PipelineContext) -> None:
            raise StageSkipRequested("cached elsewhere")

    result = Pipeline([SkippingStage()], bus=bus).run(ctx)
    assert result.success is True
    assert result.stage_results[0].outcome == "skipped"


def test_stop_event_cancels_remaining_stages(bus, ctx):
    import threading

    slow = RecordingStage("slow", sleep=0.15)
    after = RecordingStage("after")
    stop_event = threading.Event()
    pipeline = Pipeline([slow, after], bus=bus)
    threading.Timer(0.05, stop_event.set).start()
    result = pipeline.run(ctx, stop_event=stop_event)
    # 'slow' started before cancellation and completed; 'after' must be cancelled.
    assert result.cancelled is True
    assert result.stage_results[-1].outcome == "cancelled"
    assert after.calls == 0


def test_empty_pipeline_rejected(bus):
    with pytest.raises(ValueError):
        Pipeline([], bus=bus)
