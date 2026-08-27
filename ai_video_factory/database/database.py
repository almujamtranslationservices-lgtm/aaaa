"""SQLite connection + schema migrations.

Design notes
------------
* WAL journal mode for reliable concurrent reads while workers write.
* ``check_same_thread=False`` plus an internal lock — background tasks
  persist state from the worker pool.
* ``PRAGMA user_version`` tracks the schema version; every future change
  adds an incremental migration (never edits old migrations in place).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from ai_video_factory.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    video_type       TEXT NOT NULL,
    aspect_ratio     TEXT NOT NULL,
    resolution       TEXT NOT NULL,
    fps              INTEGER NOT NULL,
    target_duration  REAL NOT NULL,
    idea             TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'draft',
    language         TEXT NOT NULL DEFAULT 'ar',
    project_dir      TEXT NOT NULL,
    project_file     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    age                 TEXT, gender TEXT, height TEXT, face TEXT, hair TEXT,
    eyes                TEXT, skin TEXT, clothes TEXT, body TEXT,
    personality         TEXT, voice TEXT, visual_style TEXT,
    prompt_description  TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS scenes (
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scene_id            INTEGER NOT NULL,
    position            INTEGER NOT NULL,
    title               TEXT,
    duration            REAL NOT NULL,
    narration           TEXT,
    visual_description  TEXT,
    camera              TEXT,
    lighting            TEXT,
    environment         TEXT,
    action              TEXT,
    characters_json     TEXT,
    image_prompt        TEXT,
    video_prompt        TEXT,
    sfx                 TEXT,
    music               TEXT,
    transition          TEXT,
    status              TEXT,
    assets_json         TEXT,
    PRIMARY KEY (project_id, scene_id)
);

CREATE TABLE IF NOT EXISTS prompts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT REFERENCES projects(id) ON DELETE CASCADE,
    scene_id    INTEGER,
    kind        TEXT NOT NULL,          -- script | image | video | seo | thumbnail
    content     TEXT NOT NULL,
    provider    TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scene_id    INTEGER,
    kind        TEXT NOT NULL,          -- image | video | voice | sfx | music | subtitle
    path        TEXT NOT NULL,
    sha256      TEXT,
    size_bytes  INTEGER,
    created_at  TEXT NOT NULL,
    UNIQUE (project_id, scene_id, kind)
);

CREATE TABLE IF NOT EXISTS tasks (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    status         TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    max_retries    INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    result         TEXT,
    metadata_json  TEXT,
    created_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS providers (
    kind             TEXT NOT NULL,
    provider_id      TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    model            TEXT,
    endpoint         TEXT,
    api_key_env      TEXT,
    last_status      TEXT,
    last_checked_at  TEXT,
    PRIMARY KEY (kind, provider_id)
);

CREATE TABLE IF NOT EXISTS render_jobs (
    id             TEXT PRIMARY KEY,
    project_id     TEXT REFERENCES projects(id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'queued',
    progress       REAL NOT NULL DEFAULT 0.0,
    current_stage  TEXT,
    output_path    TEXT,
    error          TEXT,
    started_at     TEXT,
    finished_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_scenes_project  ON scenes(project_id, position);
CREATE INDEX IF NOT EXISTS idx_assets_project  ON assets(project_id, scene_id);
CREATE INDEX IF NOT EXISTS idx_prompts_project ON prompts(project_id, scene_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
"""


class Database:
    """Thread-safe SQLite access object with versioned migrations."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        try:
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error as exc:
            raise DatabaseError(f"Cannot open database at {self.path}: {exc}") from exc
        self.migrate()

    # --------------------------------------------------------------- migrations
    def migrate(self) -> None:
        """Apply pending schema migrations in order."""
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current >= SCHEMA_VERSION:
                return
            try:
                if current < 1:
                    self._conn.executescript(_SCHEMA_V1)
                    logger.info("Applied schema v1 to %s", self.path)
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._conn.commit()
            except sqlite3.Error as exc:
                self._conn.rollback()
                raise DatabaseError(f"Migration to v{SCHEMA_VERSION} failed: {exc}") from exc

    # ------------------------------------------------------------------ access
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        """Run a write statement (auto-commit) under the internal lock."""
        with self._lock:
            try:
                cursor = self._conn.execute(sql, params)
                self._conn.commit()
                return cursor
            except sqlite3.Error as exc:
                self._conn.rollback()
                raise DatabaseError(f"SQL failed: {exc} | statement: {sql[:120]}") from exc

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        """Run a read-only query and return all rows."""
        with self._lock:
            try:
                return self._conn.execute(sql, params).fetchall()
            except sqlite3.Error as exc:
                raise DatabaseError(f"SQL query failed: {exc} | statement: {sql[:120]}") from exc

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---------------------------------------------------------------- lifecycle
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
