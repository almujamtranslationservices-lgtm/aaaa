"""Prompts for refining / expanding individual scenes (Scene Generator, §6)."""

from __future__ import annotations

import json
from typing import Any

from ai_video_factory.models.scene import Scene


def build_scene_system_prompt(*, language: str = "ar") -> str:
    """System prompt for regenerating or enriching a single scene."""
    return f"""You are a scene director. You refine ONE scene of an existing video script.
Return ONE valid JSON object (no markdown, no commentary) with exactly these keys:
"narration" (in LANGUAGE={language}), "visual_description", "environment", "action",
"camera", "lighting", "image_prompt", "video_prompt", "sfx", "music", "transition"
(one of: cut, fade, dissolve, slide, zoom), "duration" (seconds).
Everything except "narration" is written in English. Strict JSON: double quotes, no trailing commas."""


def build_scene_user_prompt(scene: Scene, *, instruction: str = "") -> str:
    """User prompt asking for an improved version of *scene*."""
    current = json.dumps(
        {
            "scene_id": scene.scene_id,
            "title": scene.title,
            "duration": scene.duration,
            "narration": scene.narration,
            "visual_description": scene.visual_description,
            "environment": scene.environment,
            "action": scene.action,
            "camera": scene.camera,
            "lighting": scene.lighting,
        },
        ensure_ascii=False,
        indent=2,
    )
    return f"Current scene:\n{current}\n\nInstruction: {instruction or 'Improve pacing and visual storytelling.'}\nReturn ONLY the JSON object."
