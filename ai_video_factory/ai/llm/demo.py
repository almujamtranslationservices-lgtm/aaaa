"""Offline demo LLM provider (DEMO MODE, spec §36).

Produces a *valid, structured* script JSON from the markers embedded by
``prompts.script_prompt.build_script_user_prompt`` (VIDEO IDEA / LANGUAGE /
TARGET DURATION / SCENES). No network, no keys — lets the whole pipeline be
exercised before any real provider is configured.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest

_IDEA_RE = re.compile(r"VIDEO IDEA:\s*\n(.+?)(?:\n\s*\n|\nLANGUAGE:)", re.DOTALL)
_LANGUAGE_RE = re.compile(r"LANGUAGE:\s*(\S+)")
_DURATION_RE = re.compile(r"TARGET DURATION \(seconds\):\s*(\d+)")
_SCENES_RE = re.compile(r"SCENES:\s*(\d+)")

_AR_VISUALS = [
    "wide establishing shot of the mysterious location, moody atmosphere",
    "medium shot of the main character looking into the distance, tense expression",
    "close-up detail of a significant object, shallow depth of field",
    "dramatic wide shot with fog and volumetric light",
    "over-the-shoulder shot revealing a hidden clue",
    "aerial view of the landscape at golden hour",
]
_AR_CAMERAS = [
    "slow cinematic push-in", "static wide shot", "slow pan to the right",
    "handheld sway, documentary feel", "slow tilt up", "gentle dolly forward",
]
_AR_NARRATION = [
    "كل شيء بدأ في ليلة هادئة، حين لفت انتباه الجميع أمرٌ غريب لم يفهمه أحد.",
    "مع مرور الوقت، بدأت التفاصيل الصغيرة تكشف شيئًا أكبر مما كان متوقعًا.",
    "الشهادات تضاربت، لكن خيطًا واحدًا ظل يربط كل الروايات معًا.",
    "ثم ظهر الدليل الذي غيّر فهم الجميع لما حدث فعلًا.",
    "في تلك اللحظة، أصبحت الحقيقة أقرب مما تخيله أحد.",
    "بعد كل هذه السنوات، تبقى الأسئلة أكثر من الأجوبة… لكن النهاية ستدهشك.",
]
_EN_NARRATION = [
    "It all began on a quiet night, when something strange caught everyone's attention.",
    "As time passed, small details began to reveal something far bigger than expected.",
    "The testimonies conflicted, yet a single thread connected every story.",
    "Then came the evidence that changed how everyone understood what really happened.",
    "In that moment, the truth came closer than anyone imagined.",
    "After all these years, questions remain — but the ending will surprise you.",
]


class DemoLLMProvider(LLMProvider):
    """Deterministic offline mock used by DEMO MODE."""

    id = "demo"

    async def generate(self, request: LLMRequest) -> str:
        idea = self._extract(request.user, _IDEA_RE) or "an untold mysterious story"
        language = (self._extract(request.user, _LANGUAGE_RE) or "ar").lower()
        duration = int(self._extract(request.user, _DURATION_RE) or 60)
        scene_count = int(self._extract(request.user, _SCENES_RE) or max(3, min(10, duration // 5)))

        scene_duration = round(max(2.0, duration / scene_count), 1)
        is_arabic = language.startswith("ar")
        narrations = _AR_NARRATION if is_arabic else _EN_NARRATION
        idea_snippet = idea.strip().rstrip(".،")

        scenes: list[dict[str, Any]] = []
        for index in range(scene_count):
            visual = _AR_VISUALS[index % len(_AR_VISUALS)]
            camera = _AR_CAMERAS[index % len(_AR_CAMERAS)]
            narration = narrations[index % len(narrations)]
            if index == 0:
                narration = idea_snippet[:180] + ("…" if len(idea_snippet) > 180 else "")
            scenes.append({
                "scene_id": index + 1,
                "duration": scene_duration,
                "narration": narration,
                "visual_description": visual,
                "image_prompt": f"cinematic {visual}, dramatic lighting, photorealistic, highly detailed",
                "video_prompt": f"{camera}, subtle motion, consistent scene",
                "sfx": "ambient atmosphere" if index % 2 else "soft wind",
                "music": "dark cinematic ambient, low strings",
                "camera": camera,
            })

        title = idea_snippet[:70] if is_arabic else idea_snippet[:70].title()
        hook = (f"قصة {idea_snippet[:60]}… الحقيقة لم تُروَ بعد." if is_arabic
                else f"The story of {idea_snippet[:60]}… the truth was never told.")
        return json.dumps({"title": title, "hook": hook, "scenes": scenes}, ensure_ascii=False)

    @staticmethod
    def _extract(text: str, pattern: re.Pattern[str]) -> str | None:
        match = pattern.search(text)
        return match.group(1).strip() if match else None
