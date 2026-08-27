"""Prompt component models — the structured 15-part image prompt contract.

Every image prompt is assembled from the same ordered components (spec §10):
Subject → Character Description → Environment → Action → Camera → Lens →
Composition → Lighting → Color Grading → Depth of Field → Atmosphere →
Realism → Cinematic Style → Resolution → Aspect Ratio (+ Negative prompt).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: Shared negative-prompt defaults (extend per provider as needed).
DEFAULT_NEGATIVE_PROMPT: str = (
    "blurry, low quality, lowres, jpeg artifacts, watermark, signature, text, "
    "deformed hands, extra fingers, mutated limbs, bad anatomy, extra limbs, "
    "oversaturated, flat lighting, cropped head"
)

#: Fallback values used by the prompt engine when a scene leaves a slot empty.
DEFAULT_COMPONENT_HINTS: dict[str, str] = {
    "lens": "35mm lens",
    "composition": "cinematic rule-of-thirds composition",
    "depth_of_field": "shallow depth of field",
    "lighting": "dramatic cinematic lighting",
    "color_grading": "teal and orange color grading",
    "atmosphere": "cinematic atmosphere, volumetric light",
    "realism": "photorealistic, ultra-detailed, sharp focus",
    "cinematic_style": "cinematic film still, dramatic mood",
}

_COMPONENT_ORDER: tuple[str, ...] = (
    "subject",
    "character_block",
    "environment",
    "action",
    "camera",
    "lens",
    "composition",
    "lighting",
    "color_grading",
    "depth_of_field",
    "atmosphere",
    "realism",
    "cinematic_style",
    "resolution",
    "aspect_ratio",
)


class PromptComponents(BaseModel):
    """Ordered prompt slots; empty slots are skipped when rendering."""

    subject: str = ""
    character_descriptions: list[str] = Field(default_factory=list)
    environment: str = ""
    action: str = ""
    camera: str = ""
    lens: str = ""
    composition: str = ""
    lighting: str = ""
    color_grading: str = ""
    depth_of_field: str = ""
    atmosphere: str = ""
    realism: str = ""
    cinematic_style: str = ""
    resolution: str = ""
    aspect_ratio: str = ""
    negative_prompt: str = ""

    def render(self) -> str:
        """Render the final positive prompt, then the negative prompt."""
        character_block = "; ".join(desc.rstrip(" .") for desc in self.character_descriptions if desc.strip())
        values: dict[str, str] = {
            "subject": self.subject.strip(),
            "character_block": character_block,
        }
        for key in _COMPONENT_ORDER:
            if key not in ("subject", "character_block"):
                values[key] = getattr(self, key).strip()
        parts = [values[key] for key in _COMPONENT_ORDER if values.get(key)]
        prompt = ", ".join(parts)
        if self.negative_prompt.strip():
            prompt = f"{prompt} | Negative prompt: {self.negative_prompt.strip()}"
        return prompt
