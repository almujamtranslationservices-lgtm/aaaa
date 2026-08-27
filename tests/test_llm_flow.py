"""Tests: demo LLM provider end-to-end (script JSON contract) + factory."""

from __future__ import annotations

import asyncio
import json

import pytest

from ai_video_factory.ai.factory import create_llm_provider
from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.ai.llm.demo import DemoLLMProvider
from ai_video_factory.core.exceptions import (
    ProviderNotImplementedError,
    ScriptValidationError,
)
from ai_video_factory.models.scene import Script
from ai_video_factory.prompts.script_prompt import (
    build_script_system_prompt,
    build_script_user_prompt,
)


def _build_request(idea: str, duration: float = 30) -> LLMRequest:
    return LLMRequest(
        system=build_script_system_prompt(language="ar", target_duration=duration),
        user=build_script_user_prompt(idea, target_duration=duration, language="ar"),
    )


def test_demo_llm_full_script_flow():
    provider = DemoLLMProvider()
    request = _build_request("قصة اختفاء غامض حدث منذ 100 عام ولم يعرف أحد الحقيقة حتى اليوم.", duration=30)
    raw = asyncio.run(provider.generate(request))
    script = Script.from_llm_text(raw)  # parse + validate (auto-repair path)
    assert script.title
    assert script.scene_count >= 3
    assert script.total_duration == pytest.approx(30.0, abs=script.scene_count * 0.5)
    assert all(scene.narration for scene in script.scenes)


def test_generate_json_returns_parsed_dict_with_fences():
    class FencedDummy(LLMProvider):
        id = "fenced"

        async def generate(self, request: LLMRequest) -> str:
            return "intro text\n```json\n{'a': 1,}\n```"

    provider = FencedDummy()
    data = asyncio.run(provider.generate_json(LLMRequest(system="s", user="u")))
    assert data == {"a": 1}


def test_factory_creates_demo_llm():
    provider = create_llm_provider("demo")
    assert isinstance(provider, DemoLLMProvider)


def test_factory_rejects_unimplemented_providers_with_phase_info():
    """Every provider in the registry is implemented as of PHASE 9 — the guard
    still fires for unknown ids."""
    from ai_video_factory.ai.factory import create_llm_provider

    with pytest.raises(KeyError):
        create_llm_provider("does-not-exist-yet")


def test_factory_rejects_unknown_provider():
    with pytest.raises(KeyError):
        create_llm_provider("nonexistent")


def test_script_validation_error_type():
    with pytest.raises(ScriptValidationError):
        Script.from_llm_text(json.dumps({"title": "t", "scenes": []}))
