"""System/user prompts for the AI Script Generator (spec §7).

The generated script must be **structured JSON** — never free text. The
prompt pins the exact schema, the narration language, and the rule that
image/video prompts are written in English (image models perform better),
while keeping the JSON itself ASCII-safe.
"""

from __future__ import annotations

import math

from ai_video_factory.models.character import Character

SCRIPT_JSON_EXAMPLE = """\
{
  "title": "The Vanishing of 1924",
  "hook": "A hundred years later, the truth finally surfaces.",
  "scenes": [
    {
      "scene_id": 1,
      "duration": 5,
      "narration": "في ذلك المساء البارد من عام 1924، اختفت العائلة بأكملها دون أثر.",
      "visual_description": "an old wooden house on a foggy hill at dusk, single lit window",
      "image_prompt": "cinematic wide shot of an old wooden house on a foggy hill at dusk, single lit window, photorealistic",
      "video_prompt": "slow push-in toward the lit window, fog drifting",
      "sfx": "distant wind, creaking wood",
      "music": "dark ambient, low strings",
      "camera": "wide establishing shot, slow push-in"
    }
  ]
}"""


def estimate_scene_count(target_duration: float, scene_duration: float = 5.0) -> int:
    """Rough scene count for a target duration (3 … 40 scenes)."""
    return max(3, min(40, math.ceil(target_duration / max(2.0, scene_duration))))


def build_script_system_prompt(
    *,
    language: str = "ar",
    video_type: str = "youtube_video",
    target_duration: float = 60.0,
    scene_count_hint: int | None = None,
) -> str:
    """System prompt enforcing the strict JSON script contract."""
    scene_count = scene_count_hint or estimate_scene_count(target_duration)
    return f"""You are a senior video scriptwriter and creative director.
Write a complete narration script for a {video_type.replace('_', ' ')} video.

OUTPUT RULES (critical):
1. Respond with ONE valid JSON object and NOTHING else — no markdown, no code fences, no commentary.
2. Top-level keys: "title", "hook", "scenes".
3. "title": short, compelling (max 70 characters). "hook": one gripping opening line.
4. "scenes": exactly {scene_count} scene objects with these keys:
   "scene_id" (int, starting at 1), "duration" (seconds, 2-15), "narration",
   "visual_description", "image_prompt", "video_prompt", "sfx", "music", "camera".
5. The SUM of all scene durations must be ≈ {int(target_duration)} seconds.
6. "narration" is written in LANGUAGE={language}. Keep each narration 1-2 sentences,
   spoken style, suitable for text-to-speech.
7. "visual_description", "image_prompt", "video_prompt", "sfx", "music", "camera" are in ENGLISH.
8. "image_prompt" must be a self-contained English image-generation prompt
   (subject, environment, lighting, camera, style). Do NOT include the character's
   full description every time — the system appends it automatically.
9. Strict JSON syntax: double quotes, no trailing commas, no comments.

JSON shape example (abridged):
{SCRIPT_JSON_EXAMPLE}"""


def build_script_user_prompt(
    idea: str,
    *,
    characters: list[Character] | None = None,
    target_duration: float = 60.0,
    scene_count_hint: int | None = None,
    language: str = "ar",
) -> str:
    """User prompt carrying the idea, character bible and planning numbers.

    The marker lines (VIDEO IDEA / LANGUAGE / TARGET DURATION / SCENES) are
    also parsed by the offline DemoLLMProvider, so demo mode exercises the
    exact same contract as real providers.
    """
    scene_count = scene_count_hint or estimate_scene_count(target_duration)
    lines = [
        "Write the script for the following video.",
        "",
        f"VIDEO IDEA:\n{idea.strip()}",
        "",
        f"LANGUAGE: {language}",
        f"TARGET DURATION (seconds): {int(target_duration)}",
        f"SCENES: {scene_count}",
    ]
    if characters:
        bible = "\n".join(f"- {character.to_prompt_description()}" for character in characters)
        lines += [
            "",
            "CHARACTERS BIBLE (keep these characters visually consistent in every scene; "
            "reference them by name in the scene descriptions):",
            bible,
        ]
    lines += ["", "Return ONLY the JSON object now."]
    return "\n".join(lines)
