"""Character Bible — the consistency system.

Characters are described once, in structured fields, and rendered into a
compact natural-language description that every image/video prompt generator
injects automatically. This is what keeps a character looking the same across
all scenes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Character(BaseModel):
    """One entry of the project's Character Bible."""

    name: str = Field(min_length=1, max_length=80)
    age: str = ""
    gender: str = ""
    height: str = ""
    face: str = ""
    hair: str = ""
    eyes: str = ""
    skin: str = ""
    clothes: str = ""
    body: str = ""
    personality: str = ""
    voice: str = ""
    visual_style: str = ""

    def to_prompt_description(self) -> str:
        """Render the character as compact prompt text (consistency block).

        Example::

            Omar: 35-year-old male, tall (190cm), athletic build, angular face
            with a scar on the left cheek, short black hair, brown eyes, olive
            skin, wearing a dark wool coat; personality: calm and mysterious;
            visual style: photorealistic.
        """
        physical: list[str] = []
        age = self.age.strip()
        gender = self.gender.strip()
        if age and gender:
            physical.append(f"{age}-year-old {gender}")
        elif age:
            physical.append(f"{age} years old")
        elif gender:
            physical.append(gender)
        for feature in (self.height, self.body, self.face, self.hair, self.eyes, self.skin, self.clothes):
            if feature and feature.strip():
                physical.append(feature.strip())

        parts = [f"{self.name}: {', '.join(physical)}" if physical else self.name]
        if self.personality.strip():
            parts.append(f"personality: {self.personality.strip()}")
        if self.voice.strip():
            parts.append(f"voice: {self.voice.strip()}")
        if self.visual_style.strip():
            parts.append(f"visual style: {self.visual_style.strip()}")
        return "; ".join(parts) + "."
