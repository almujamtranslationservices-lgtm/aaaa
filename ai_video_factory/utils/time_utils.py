"""Time helpers: formatting, SRT/ASS timestamps, ETA estimation."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat()


def format_duration(seconds: float) -> str:
    """``95.0 → "01:35"``, ``3671 → "1:01:11"``."""
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def srt_timestamp(seconds: float) -> str:
    """``83.4 → "00:01:23,400"`` (SRT comma-millisecond format)."""
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def ass_timestamp(seconds: float) -> str:
    """``83.4 → "0:01:23.40"`` (ASS centisecond format)."""
    centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, cs = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def estimate_eta(elapsed_s: float, progress: float) -> float | None:
    """Estimated total remaining seconds, or ``None`` when progress is ~0."""
    if progress <= 0.001:
        return None
    remaining_fraction = max(0.0, 1.0 - min(1.0, progress))
    return elapsed_s * (remaining_fraction / progress)


def format_eta(seconds: float | None) -> str:
    """Human-friendly ETA, e.g. ``"≈ 2m 30s"``."""
    if seconds is None:
        return "—"
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"≈ {seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"≈ {minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"≈ {hours}h {minutes:02d}m"
