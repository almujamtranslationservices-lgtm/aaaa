"""Central exception hierarchy for AI Video Factory.

Every domain-specific error inherits from :class:`AVFError` so callers can
catch a single base class at UI boundaries while handlers deeper in the stack
can react to precise error types (retry / skip / cancel…).
"""

from __future__ import annotations

from typing import Any


class AVFError(Exception):
    """Base class for all application errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = details or {}


# --------------------------------------------------------------- configuration
class ConfigError(AVFError):
    """Invalid or missing configuration."""


# --------------------------------------------------------------------- project
class ProjectError(AVFError):
    """Project lifecycle error (create / save / load / delete)."""


class ProjectNotFoundError(ProjectError):
    """A project id or path could not be resolved."""


# -------------------------------------------------------------------- database
class DatabaseError(AVFError):
    """SQLite persistence error."""


# ------------------------------------------------------------------ validation
class DataValidationError(AVFError):
    """Generic payload validation failure."""


class JSONRepairError(DataValidationError):
    """LLM output could not be parsed into JSON even after auto-repair."""


class ScriptValidationError(DataValidationError):
    """Parsed JSON does not satisfy the script schema."""


# -------------------------------------------------------------------- providers
class ProviderError(AVFError):
    """Base class for AI provider failures."""

    def __init__(self, message: str, *, provider: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.provider = provider


class ProviderNotConfiguredError(ProviderError):
    """Provider selected but missing its API key / endpoint."""


class ProviderNotImplementedError(ProviderError):
    """Provider registered for a future phase and not yet available."""

    def __init__(self, message: str, *, provider: str | None = None, planned_phase: int | None = None) -> None:
        super().__init__(message, provider=provider)
        self.planned_phase = planned_phase


class ProviderConnectionError(ProviderError):
    """Could not reach the provider endpoint."""


class ProviderResponseError(ProviderError):
    """Provider responded, but the response was unusable."""


# ---------------------------------------------------------------------- ffmpeg
class FFmpegError(AVFError):
    """FFmpeg execution / setup failure."""


class FFmpegNotFoundError(FFmpegError):
    """No usable ffmpeg binary could be located."""


# -------------------------------------------------------------------- pipeline
class PipelineError(AVFError):
    """Pipeline orchestration failure."""


class StageSkipRequested(PipelineError):
    """A stage may raise this to gracefully mark itself as skipped."""


# ----------------------------------------------------------------------- tasks
class TaskCancelledError(AVFError):
    """Cooperative cancellation requested for a background task."""
