"""Image Prompt Engine — assembles the 15-component cinematic prompt (spec §10).

Rules enforced here
-------------------
* Character descriptions from the Character Bible are injected exactly once
  per prompt (never duplicated) for every character referenced by the scene.
* Empty slots fall back to cinematic defaults (lens, composition, DOF…) so
  prompts stay complete even when the LLM left fields blank.
* The negative prompt is standardised and appended last.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_video_factory.models.character import Character
from ai_video_factory.models.prompt import DEFAULT_COMPONENT_HINTS, DEFAULT_NEGATIVE_PROMPT, PromptComponents
from ai_video_factory.models.project import AspectRatio, ResolutionPreset, resolution_dims
from ai_video_factory.models.scene import Scene

_RESOLUTION_WORDS: dict[ResolutionPreset, str] = {
    ResolutionPreset.P480: "standard definition",
    ResolutionPreset.P720: "HD 720p",
    ResolutionPreset.P1080: "full HD 1080p",
    ResolutionPreset.P4K: "ultra HD 4K, 8k quality",
}


class PromptStyleOverrides(BaseModel):
    """Optional per-project style tweaks applied on top of scene fields."""

    cinematic_style: str = ""
    color_grading: str = ""
    realism: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


class ImagePromptEngine:
    """Builds complete image prompts from a scene + character bible."""

    def __init__(self, *, negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
                 overrides: PromptStyleOverrides | None = None) -> None:
        self._negative = negative_prompt
        self._overrides = overrides or PromptStyleOverrides()

    # ------------------------------------------------------------------ build
    def build(
        self,
        scene: Scene,
        *,
        characters: list[Character] | None = None,
        resolution: ResolutionPreset = ResolutionPreset.P1080,
        aspect_ratio: AspectRatio = AspectRatio.R_16_9,
    ) -> tuple[str, str]:
        """Return ``(positive_prompt, negative_prompt)`` for *scene*."""
        characters = characters or []
        width, height = resolution_dims(resolution, aspect_ratio)

        subject = (scene.image_prompt or scene.visual_description or scene.title or f"Scene {scene.scene_id}").strip()
        environment = scene.environment.strip()
        character_block = self._character_block(scene, characters, subject)

        components = PromptComponents(
            subject=subject,
            character_descriptions=character_block,
            environment=environment or self._extract_environment(scene),
            action=scene.action.strip(),
            camera=scene.camera.strip(),
            lens=self._default("lens"),
            composition=self._default("composition"),
            lighting=scene.lighting.strip() or self._default("lighting"),
            color_grading=self._overrides.color_grading or self._default("color_grading"),
            depth_of_field=self._default("depth_of_field"),
            atmosphere=self._default("atmosphere"),
            realism=self._overrides.realism or self._default("realism"),
            cinematic_style=self._overrides.cinematic_style or self._default("cinematic_style"),
            resolution=f"{_RESOLUTION_WORDS[resolution]}, {width}x{height}",
            aspect_ratio=f"{aspect_ratio.value} aspect ratio",
            negative_prompt=self._negative,
        )
        return components.render(), self._negative

    # -------------------------------------------------------------- internals
    def _default(self, key: str) -> str:
        return self._overrides.extra.get(key) or DEFAULT_COMPONENT_HINTS.get(key, "")

    @staticmethod
    def _extract_environment(scene: Scene) -> str:
        """Fall back to the visual description when environment is empty."""
        return scene.visual_description.strip()

    @staticmethod
    def _character_block(scene: Scene, characters: list[Character], subject: str) -> list[str]:
        """Descriptions for scene-referenced characters — injected once each.

        Only characters explicitly referenced by the scene are injected (a
        scene with no characters features none of them). A description is
        additionally skipped when already contained in the subject (prevents
        the duplicated-character-description bug, spec §10).
        """
        referenced = set(scene.characters)
        if not referenced:
            return []
        descriptions: list[str] = []
        for character in characters:
            if character.name not in referenced:
                continue
            description = character.to_prompt_description()
            if description in subject:
                continue  # already present — never duplicate
            descriptions.append(description)
        return descriptions

    # ------------------------------------------------------------- thumbnails
    def build_thumbnail_prompt(self, *, title: str, hook: str = "",
                               aspect: str = "16:9") -> str:
        """YouTube-optimised thumbnail prompt (1280x720, spec §28)."""
        components = PromptComponents(
            subject=f"bold YouTube thumbnail composition for '{title[:60]}'" + (f" — {hook[:60]}" if hook else ""),
            composition="high-contrast focal subject, strong depth separation, click-worthy framing",
            lighting="dramatic key lighting",
            color_grading="vibrant, saturated colours",
            depth_of_field="subject pops from a slightly blurred background",
            realism="photorealistic",
            cinematic_style="eye-catching poster style",
            resolution="1280x720",
            aspect_ratio=f"{aspect} aspect ratio",
            negative_prompt=self._negative,
        )
        return components.render()
