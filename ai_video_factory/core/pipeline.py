"""Rendering / generation pipeline orchestration.

A :class:`Pipeline` is an ordered list of :class:`PipelineStage` objects
executed against a shared :class:`PipelineContext`. Progress is published on
the event bus as *real* weighted percentages, matching the UX contract:

    Generating Script       10%
    Generating Scenes       20%
    Generating Images       40%
    Generating Videos       60%
    Generating Voice        70%
    Rendering               90%
    Completed               100%

``PIPELINE_PLAN`` documents the full 15-stage plan from the specification;
the concrete stages are implemented phase by phase (image stages in PHASE 7,
voice in PHASE 9, rendering in PHASE 13…) and assembled by
``build_standard_pipeline`` once available.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.exceptions import StageSkipRequested
from ai_video_factory.models.project import Project

logger = logging.getLogger(__name__)

# (stage name, weight, delivery phase) — weights sum to 100.
PIPELINE_PLAN: tuple[tuple[str, float, int], ...] = (
    ("script.generate",    10.0, 5),
    ("script.validate",     3.0, 5),
    ("scenes.build",        7.0, 6),
    ("prompts.generate",    5.0, 6),
    ("images.generate",    15.0, 7),
    ("videos.generate",    15.0, 8),
    ("voice.generate",       7.0, 9),
    ("audio.sfx",            3.0, 10),
    ("audio.mix",           3.0, 10),   # music bed + ducked scene mixes
    ("subtitles.generate",   4.0, 11),
    ("timeline.assemble",    3.0, 13),
    ("video.render",        12.0, 13),
    ("thumbnail.generate",   4.0, 15),
    ("seo.generate",         4.0, 14),
    ("export.final",         5.0, 13),
)

StageOutcome = Literal["ok", "skipped", "failed", "cancelled"]


class PipelineStage(ABC):
    """One step of the pipeline.

    Class attributes:
        name: unique stage identifier (used in events and logs).
        weight: contribution to overall progress (relative, not percent).
        on_error: ``abort`` stops the pipeline, ``skip`` continues, ``retry``
            retries the stage before applying the previous policies.
        max_retries: extra attempts when ``on_error == "retry"``.
    """

    name: str = "stage"
    weight: float = 1.0
    on_error: Literal["abort", "skip", "retry"] = "abort"
    max_retries: int = 0

    @abstractmethod
    def run(self, ctx: "PipelineContext") -> None:
        """Execute the stage. Raise to signal failure."""

    def should_skip(self, ctx: "PipelineContext") -> bool:
        """Return ``True`` when cached results make this stage unnecessary."""
        return False


@dataclass
class PipelineContext:
    """Shared state carried through every stage of one pipeline run."""

    project: Project
    workdir: Path
    data: dict[str, Any] = field(default_factory=dict)      # script, seo, …
    artifacts: dict[str, Path] = field(default_factory=dict)  # key → file path
    _progress_hook: Callable[[float, str], None] | None = field(default=None, repr=False)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def report_progress(self, fraction: float, message: str = "") -> None:
        """Let a stage report its internal progress (0.0 … 1.0)."""
        if self._progress_hook is not None:
            self._progress_hook(min(1.0, max(0.0, fraction)), message)


@dataclass
class StageResult:
    name: str
    outcome: StageOutcome
    duration_s: float = 0.0
    error: str | None = None


@dataclass
class PipelineResult:
    stage_results: list[StageResult] = field(default_factory=list)
    success: bool = False
    cancelled: bool = False
    error: str | None = None
    elapsed_s: float = 0.0

    @property
    def completed_stages(self) -> list[str]:
        return [result.name for result in self.stage_results if result.outcome == "ok"]


class Pipeline:
    """Weighted, cancellable, event-driven stage runner."""

    def __init__(self, stages: list[PipelineStage], *, bus: EventBus) -> None:
        if not stages:
            raise ValueError("A pipeline needs at least one stage")
        self._stages = list(stages)
        self._bus = bus
        self._total_weight = sum(stage.weight for stage in self._stages) or 1.0

    # ------------------------------------------------------------------- run
    def run(self, ctx: PipelineContext, *, stop_event: threading.Event | None = None) -> PipelineResult:
        """Execute all stages in order, publishing progress along the way."""
        started = time.perf_counter()
        completed_weight = 0.0
        result = PipelineResult()
        stage_names = [stage.name for stage in self._stages]
        self._bus.publish("pipeline.started", stages=stage_names,
                          project_id=ctx.project.id, project_name=ctx.project.name)

        for stage in self._stages:
            if stop_event is not None and stop_event.is_set():
                result.cancelled = True
                result.stage_results.append(StageResult(stage.name, "cancelled"))
                logger.info("Pipeline cancelled before stage '%s'", stage.name)
                break

            percent_before = self._percent(completed_weight)
            if stage.should_skip(ctx):
                duration = 0.0
                result.stage_results.append(StageResult(stage.name, "skipped", duration))
                completed_weight += stage.weight
                self._publish_progress(ctx, stage, completed_weight, skipped=True)
                logger.info("Stage '%s' skipped (cache hit)", stage.name)
                continue

            self._bus.publish("pipeline.stage.started", stage=stage.name,
                              percent=round(percent_before, 1), project_id=ctx.project.id)
            ctx._progress_hook = self._make_hook(stage, completed_weight)

            attempt = 0
            while True:
                attempt += 1
                stage_start = time.perf_counter()
                try:
                    stage.run(ctx)
                except StageSkipRequested as exc:
                    result.stage_results.append(
                        StageResult(stage.name, "skipped", time.perf_counter() - stage_start, str(exc))
                    )
                    completed_weight += stage.weight
                    self._publish_progress(ctx, stage, completed_weight, skipped=True)
                    break
                except Exception as exc:  # noqa: BLE001 — stage boundary
                    error = f"{type(exc).__name__}: {exc}"
                    logger.exception("Stage '%s' failed (attempt %d): %s", stage.name, attempt, error)
                    if stage.on_error == "retry" and attempt <= stage.max_retries:
                        self._bus.publish("pipeline.stage.retry", stage=stage.name,
                                          attempt=attempt, max_attempts=1 + stage.max_retries, error=error)
                        continue
                    result.stage_results.append(
                        StageResult(stage.name, "failed", time.perf_counter() - stage_start, error)
                    )
                    if stage.on_error == "skip":
                        # Tolerated failure: mark the stage as skipped (with the
                        # error preserved) and continue the pipeline.
                        logger.warning("Stage '%s' failed and will be skipped: %s", stage.name, error)
                        result.stage_results[-1] = StageResult(
                            stage.name, "skipped", time.perf_counter() - stage_start, error
                        )
                        completed_weight += stage.weight
                        self._publish_progress(ctx, stage, completed_weight)
                        break
                    result.error = f"Stage '{stage.name}' failed: {error}"
                    self._bus.publish("pipeline.failed", stage=stage.name, error=error,
                                      project_id=ctx.project.id)
                    result.elapsed_s = time.perf_counter() - started
                    return result
                else:
                    result.stage_results.append(
                        StageResult(stage.name, "ok", time.perf_counter() - stage_start)
                    )
                    completed_weight += stage.weight
                    self._publish_progress(ctx, stage, completed_weight)
                    self._bus.publish("pipeline.stage.completed", stage=stage.name,
                                      percent=round(self._percent(completed_weight), 1))
                    break

        result.elapsed_s = time.perf_counter() - started
        ctx._progress_hook = None
        result.cancelled = result.cancelled or bool(stop_event is not None and stop_event.is_set())
        result.success = not result.cancelled and all(
            r.outcome in ("ok", "skipped") for r in result.stage_results
        ) and len(result.stage_results) == len(self._stages)
        if result.cancelled:
            self._bus.publish("pipeline.cancelled", project_id=ctx.project.id,
                              completed=[r.name for r in result.stage_results if r.outcome == "ok"])
        else:
            self._bus.publish("pipeline.completed", success=result.success,
                              elapsed_s=round(result.elapsed_s, 2), project_id=ctx.project.id)
        return result

    # -------------------------------------------------------------- internals
    def _percent(self, weight: float) -> float:
        return 100.0 * weight / self._total_weight

    def _make_hook(self, stage: PipelineStage, completed_weight: float) -> Callable[[float, str], None]:
        def hook(fraction: float, message: str) -> None:
            percent = self._percent(completed_weight + stage.weight * fraction)
            self._bus.publish("pipeline.progress", stage=stage.name,
                              percent=round(percent, 1), message=message)
        return hook

    def _publish_progress(self, ctx: PipelineContext, stage: PipelineStage,
                          completed_weight: float, *, skipped: bool = False) -> None:
        percent = self._percent(completed_weight)
        self._bus.publish("pipeline.progress", stage=stage.name,
                          percent=round(percent, 1), skipped=skipped)
