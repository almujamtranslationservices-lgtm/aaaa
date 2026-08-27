"""Repository layer — typed data access over :class:`Database`.

Repositories speak both worlds: they accept/return domain models
(``Project``, ``Scene``, ``Character``…) where useful, and plain rows for
lightweight listings. The ``project.json`` file remains the source of truth;
the DB mirrors it for fast queries, resume support and dashboards.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence, TYPE_CHECKING

from ai_video_factory.database.database import Database
from ai_video_factory.models.character import Character
from ai_video_factory.models.scene import Scene, SceneStatus, Transition
from ai_video_factory.utils.time_utils import now_iso

if TYPE_CHECKING:
    from ai_video_factory.models.project import Project


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectRepository:
    """Projects table CRUD."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert_project(self, project: "Project", *, project_dir: Path, project_file: Path) -> None:
        self._db.execute(
            """
            INSERT INTO projects (id, name, video_type, aspect_ratio, resolution, fps,
                                  target_duration, idea, status, language,
                                  project_dir, project_file, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name, video_type = excluded.video_type,
                aspect_ratio = excluded.aspect_ratio, resolution = excluded.resolution,
                fps = excluded.fps, target_duration = excluded.target_duration,
                idea = excluded.idea, status = excluded.status, language = excluded.language,
                project_dir = excluded.project_dir, project_file = excluded.project_file,
                updated_at = excluded.updated_at
            """,
            (
                project.id, project.name, project.video_type.value, project.aspect_ratio.value,
                project.resolution.value, project.fps, project.target_duration, project.idea,
                project.status.value, project.settings.language,
                str(project_dir), str(project_file), project.created_at, project.updated_at,
            ),
        )

    def get(self, project_id: str) -> Any | None:
        return self._db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))

    def list_summaries(self, *, limit: int = 50) -> list[Any]:
        return self._db.query(
            "SELECT id, name, status, project_dir, updated_at FROM projects "
            "ORDER BY updated_at DESC LIMIT ?", (limit,)
        )

    def update_status(self, project_id: str, status: str) -> None:
        self._db.execute("UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                         (status, _now(), project_id))

    def delete(self, project_id: str) -> None:
        self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))


class SceneRepository:
    """Scenes of one project (replace-all keeps ordering simple and honest)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def replace_scenes(self, project_id: str, scenes: Sequence[Scene]) -> None:
        self._db.execute("DELETE FROM scenes WHERE project_id = ?", (project_id,))
        for position, scene in enumerate(scenes):
            self._db.execute(
                """
                INSERT INTO scenes (project_id, scene_id, position, title, duration, narration,
                                    visual_description, camera, lighting, environment, action,
                                    characters_json, image_prompt, video_prompt, sfx, music,
                                    transition, status, assets_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, scene.scene_id, position, scene.title, scene.duration,
                    scene.narration, scene.visual_description, scene.camera, scene.lighting,
                    scene.environment, scene.action, json.dumps(scene.characters, ensure_ascii=False),
                    scene.image_prompt, scene.video_prompt, scene.sfx, scene.music,
                    scene.transition.value, scene.status.value,
                    json.dumps(scene.assets, ensure_ascii=False),
                ),
            )

    def list_scenes(self, project_id: str) -> list[Scene]:
        rows = self._db.query(
            "SELECT * FROM scenes WHERE project_id = ? ORDER BY position", (project_id,)
        )
        scenes: list[Scene] = []
        for row in rows:
            data = dict(row)
            data["characters"] = json.loads(data.pop("characters_json") or "[]")
            data["assets"] = json.loads(data.pop("assets_json") or "{}")
            # Convert string columns back to enums explicitly (str-Enum fields
            # would otherwise keep the raw str and trip the pydantic serializer).
            data["transition"] = Transition(data.get("transition") or "cut")
            data["status"] = SceneStatus(data.get("status") or "pending")
            scenes.append(Scene.model_validate(data))
        return scenes


class CharacterRepository:
    """Character Bible persistence (replace-all keeps renames/deletes in sync)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def replace_characters(self, project_id: str, characters: Sequence[Character]) -> None:
        """Mirror the project's character list exactly (deletes stale rows)."""
        self._db.execute("DELETE FROM characters WHERE project_id = ?", (project_id,))
        for character in characters:
            self._insert_character(project_id, character)

    def upsert_character(self, project_id: str, character: Character) -> None:
        """Kept for compatibility; prefer :meth:`replace_characters`."""
        self._db.execute("DELETE FROM characters WHERE project_id = ? AND name = ?",
                         (project_id, character.name))
        self._insert_character(project_id, character)

    def _insert_character(self, project_id: str, character: Character) -> None:
        fields = {
            "age": character.age, "gender": character.gender, "height": character.height,
            "face": character.face, "hair": character.hair, "eyes": character.eyes,
            "skin": character.skin, "clothes": character.clothes, "body": character.body,
            "personality": character.personality, "voice": character.voice,
            "visual_style": character.visual_style,
        }
        self._db.execute(
            """
            INSERT INTO characters (project_id, name, age, gender, height, face, hair, eyes,
                                    skin, clothes, body, personality, voice, visual_style,
                                    prompt_description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, character.name, *fields.values(),
             character.to_prompt_description(), _now()),
        )

    def list_characters(self, project_id: str) -> list[Character]:
        rows = self._db.query(
            "SELECT * FROM characters WHERE project_id = ? ORDER BY name", (project_id,)
        )
        return [Character.model_validate({
            "name": row["name"], "age": row["age"] or "", "gender": row["gender"] or "",
            "height": row["height"] or "", "face": row["face"] or "", "hair": row["hair"] or "",
            "eyes": row["eyes"] or "", "skin": row["skin"] or "", "clothes": row["clothes"] or "",
            "body": row["body"] or "", "personality": row["personality"] or "",
            "voice": row["voice"] or "", "visual_style": row["visual_style"] or "",
        }) for row in rows]


class AssetRepository:
    """Generated-asset registry (cache identity via sha256)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def register(self, project_id: str, scene_id: int, kind: str, path: Path,
                 *, sha256: str | None = None, size_bytes: int | None = None) -> None:
        self._db.execute(
            """
            INSERT INTO assets (project_id, scene_id, kind, path, sha256, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, scene_id, kind) DO UPDATE SET
                path = excluded.path, sha256 = excluded.sha256,
                size_bytes = excluded.size_bytes, created_at = excluded.created_at
            """,
            (project_id, scene_id, kind, str(path), sha256, size_bytes, _now()),
        )

    def get(self, project_id: str, scene_id: int, kind: str) -> Any | None:
        return self._db.query_one(
            "SELECT * FROM assets WHERE project_id = ? AND scene_id = ? AND kind = ?",
            (project_id, scene_id, kind),
        )

    def list_for_project(self, project_id: str) -> list[Any]:
        return self._db.query(
            "SELECT * FROM assets WHERE project_id = ? ORDER BY scene_id, kind", (project_id,)
        )


class PromptRepository:
    """Prompt history (reproducibility + editing)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, project_id: str, kind: str, content: str, *,
             scene_id: int | None = None, provider: str = "") -> None:
        self._db.execute(
            "INSERT INTO prompts (project_id, scene_id, kind, content, provider, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, scene_id, kind, content, provider, _now()),
        )

    def latest(self, project_id: str, kind: str, *, scene_id: int | None = None) -> str | None:
        row = self._db.query_one(
            "SELECT content FROM prompts WHERE project_id = ? AND kind = ? AND scene_id IS ? "
            "ORDER BY id DESC LIMIT 1", (project_id, kind, scene_id),
        )
        return row["content"] if row else None


class TaskRepository:
    """Task queue persistence — satisfies TaskManager's TaskPersistence protocol."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert_task(self, task: dict[str, Any]) -> None:
        self._db.execute(
            """
            INSERT INTO tasks (id, name, status, attempts, max_retries, error, result,
                               metadata_json, created_at, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status, attempts = excluded.attempts,
                max_retries = excluded.max_retries, error = excluded.error,
                result = excluded.result, metadata_json = excluded.metadata_json,
                started_at = excluded.started_at, finished_at = excluded.finished_at
            """,
            (
                task["id"], task["name"], task["status"], task.get("attempts", 0),
                task.get("max_retries", 0), task.get("error"), task.get("result"),
                json.dumps(task.get("metadata", {}), ensure_ascii=False),
                task.get("created_at"), task.get("started_at"), task.get("finished_at"),
            ),
        )

    def get(self, task_id: str) -> Any | None:
        return self._db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))

    def pending(self) -> list[Any]:
        """Tasks that were in-flight when the app closed (resume support)."""
        return self._db.query(
            "SELECT * FROM tasks WHERE status IN ('pending', 'running', 'retrying') ORDER BY created_at"
        )


class SettingsRepository:
    """Key/value settings store (JSON values)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def set(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), _now()),
        )

    def get(self, key: str, default: Any = None) -> Any:
        row = self._db.query_one("SELECT value_json FROM settings WHERE key = ?", (key,))
        return json.loads(row["value_json"]) if row else default

    def all(self) -> dict[str, Any]:
        return {row["key"]: json.loads(row["value_json"]) for row in
                self._db.query("SELECT key, value_json FROM settings")}


class ProviderRepository:
    """Per-provider runtime state (selected model, last connection status)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, kind: str, provider_id: str, *, enabled: bool = True,
               model: str | None = None, endpoint: str | None = None,
               api_key_env: str | None = None) -> None:
        self._db.execute(
            """
            INSERT INTO providers (kind, provider_id, enabled, model, endpoint, api_key_env)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(kind, provider_id) DO UPDATE SET
                enabled = excluded.enabled, model = excluded.model,
                endpoint = excluded.endpoint, api_key_env = excluded.api_key_env
            """,
            (kind, provider_id, int(enabled), model, endpoint, api_key_env),
        )

    def set_status(self, kind: str, provider_id: str, status: str) -> None:
        self._db.execute(
            "UPDATE providers SET last_status = ?, last_checked_at = ? "
            "WHERE kind = ? AND provider_id = ?",
            (status, _now(), kind, provider_id),
        )

    def list(self, kind: str | None = None) -> list[Any]:
        if kind:
            return self._db.query("SELECT * FROM providers WHERE kind = ? ORDER BY provider_id", (kind,))
        return self._db.query("SELECT * FROM providers ORDER BY kind, provider_id")


class RenderJobRepository:
    """Rendering job tracking (progress resume across restarts)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, job_id: str, project_id: str) -> None:
        self._db.execute(
            "INSERT INTO render_jobs (id, project_id, status, progress, started_at) "
            "VALUES (?, ?, 'running', 0.0, ?)",
            (job_id, project_id, _now()),
        )

    def update_progress(self, job_id: str, progress: float, current_stage: str | None = None) -> None:
        self._db.execute(
            "UPDATE render_jobs SET progress = ?, current_stage = ? WHERE id = ?",
            (progress, current_stage, job_id),
        )

    def finish(self, job_id: str, *, status: str, output_path: str | None = None,
               error: str | None = None) -> None:
        self._db.execute(
            "UPDATE render_jobs SET status = ?, output_path = ?, error = ?, finished_at = ? "
            "WHERE id = ?", (status, output_path, error, _now(), job_id),
        )
