"""Scene and Script models.

``Script`` is the *validated* result of the LLM script generator (spec §7):
strict JSON with ``title``, ``hook`` and a list of scenes. ``Scene`` is the
richer internal model (spec §9) used throughout the app once the script has
been expanded by the Scene Generator (PHASE 6).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ai_video_factory.core.exceptions import JSONRepairError, ScriptValidationError
from ai_video_factory.utils.validation import parse_llm_json


class Transition(str, Enum):
    CUT = "cut"
    FADE = "fade"
    DISSOLVE = "dissolve"
    SLIDE = "slide"
    ZOOM = "zoom"


class SceneStatus(str, Enum):
    PENDING = "pending"
    SCRIPTED = "scripted"
    PROMPTED = "prompted"
    IMAGE_READY = "image_ready"
    VIDEO_READY = "video_ready"
    AUDIO_READY = "audio_ready"
    DONE = "done"
    FAILED = "failed"


class Scene(BaseModel):
    """Rich internal scene model (spec §9)."""

    scene_id: int = Field(ge=1)
    title: str = ""
    duration: float = Field(default=5.0, ge=0.5, le=120.0)
    narration: str = ""
    on_screen_text: str = ""
    visual_description: str = ""
    camera: str = ""
    lighting: str = ""
    environment: str = ""
    action: str = ""
    characters: list[str] = Field(default_factory=list)   # names from the Character Bible
    image_prompt: str = ""
    video_prompt: str = ""
    sfx: str = ""
    music: str = ""
    transition: Transition = Transition.CUT
    status: SceneStatus = SceneStatus.PENDING
    assets: dict[str, str] = Field(default_factory=dict)   # kind → relative path (cache registry)
    seed: int | None = None

    @field_validator("characters", mode="before")
    @classmethod
    def _unique_characters(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        seen: list[str] = []
        for item in value:
            if item is None:
                continue
            name = str(item).strip()
            if name and name not in seen:
                seen.append(name)
        return seen


class ScriptScene(BaseModel):
    """One scene exactly as agreed with the LLM contract (spec §7)."""

    scene_id: int | None = None
    duration: float = Field(default=5.0, ge=0.5, le=120.0)
    narration: str = ""
    visual_description: str = ""
    image_prompt: str = ""
    video_prompt: str = ""
    sfx: str = ""
    music: str = ""
    camera: str = ""


class Script(BaseModel):
    """Validated LLM script output."""

    title: str = Field(min_length=1)
    hook: str = ""
    scenes: list[ScriptScene] = Field(min_length=1)

    @property
    def total_duration(self) -> float:
        return round(sum(scene.duration for scene in self.scenes), 2)

    @property
    def scene_count(self) -> int:
        return len(self.scenes)

    @classmethod
    def from_llm_text(cls, text: str) -> "Script":
        """Parse, auto-repair and validate raw LLM output into a Script.

        Raises:
            JSONRepairError: the output could not be parsed as JSON.
            ScriptValidationError: JSON parsed but does not satisfy the schema.
        """
        data = parse_llm_json(text)
        if not isinstance(data, dict):
            raise ScriptValidationError("Script JSON root must be an object")

        raw_scenes = data.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ScriptValidationError("Script JSON must contain a non-empty 'scenes' array")

        title = str(data.get("title") or "").strip()
        if not title:
            raise ScriptValidationError("Script JSON must contain a non-empty 'title'")

        scenes: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_scenes, start=1):
            if not isinstance(raw, dict):
                raise ScriptValidationError(f"Scene #{index} is not a JSON object")
            raw = dict(raw)
            scene_id = raw.get("scene_id")
            raw["scene_id"] = int(scene_id) if isinstance(scene_id, (int, float)) and scene_id > 0 else index
            scenes.append(raw)

        try:
            return cls(title=title, hook=str(data.get("hook") or ""), scenes=scenes)
        except Exception as exc:  # pydantic validation → domain error
            raise ScriptValidationError(f"Script failed schema validation: {exc}") from exc

    def to_rich_scenes(self) -> list[Scene]:
        """Convert into internal :class:`Scene` models (ids renumbered 1..n)."""
        return [
            Scene(
                scene_id=index,
                title=f"Scene {index}",
                duration=scene.duration,
                narration=scene.narration,
                visual_description=scene.visual_description,
                camera=scene.camera,
                image_prompt=scene.image_prompt,
                video_prompt=scene.video_prompt,
                sfx=scene.sfx,
                music=scene.music,
                status=SceneStatus.SCRIPTED,
            )
            for index, scene in enumerate(self.scenes, start=1)
        ]
