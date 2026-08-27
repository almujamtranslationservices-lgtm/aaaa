"""Filesystem helpers: safe names, atomic writes, hashing, safe deletion."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

_UNSAFE_CHARS = re.compile(r"[^\w\-]+", re.UNICODE)


def ensure_dir(path: Path | str) -> Path:
    """Create *path* (and parents) if needed and return it."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str, *, max_length: int = 60) -> str:
    """Convert an arbitrary name (Arabic included) into a safe directory/file name."""
    name = (name or "").strip().replace(" ", "-")
    name = _UNSAFE_CHARS.sub("-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-._")
    return (name or "untitled")[:max_length]


def unique_path(path: Path) -> Path:
    """Return *path* itself, or ``<stem>-2``, ``<stem>-3``… if it already exists."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def atomic_write_text(path: Path, text: str) -> None:
    """Write text through a temp file + rename (crash-safe)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically serialise *payload* as pretty UTF-8 JSON."""
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def read_json(path: Path | str) -> Any:
    """Read a JSON file (UTF-8). Raises OSError/JSONDecodeError as-is."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def backup_file(path: Path, suffix: str = ".bak") -> Path:
    """Copy *path* to ``<name><suffix>`` if it exists (rolling single backup)."""
    path = Path(path)
    backup = path.with_name(path.name + suffix)
    if path.exists():
        shutil.copy2(path, backup)
    return backup


def sha256_file(path: Path | str, *, chunk_size: int = 1_048_576) -> str:
    """SHA-256 hex digest of a file (streamed — used for asset cache identity)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(num_bytes: float) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0 or unit == "TB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{int(num_bytes)} B"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"  # pragma: no cover


def rmtree_safe(path: Path | str, *, must_contain: Path | str | None = None) -> None:
    """Delete a directory tree with a containment guard against misuse.

    Args:
        path: directory to remove.
        must_contain: when given, *path* must live inside it or the call aborts.
    """
    path = Path(path).resolve()
    if must_contain is not None:
        allowed = Path(must_contain).resolve()
        if allowed not in path.parents and path != allowed:
            raise ValueError(f"Refusing to delete {path}: outside {allowed}")
    if path.exists():
        shutil.rmtree(path)
