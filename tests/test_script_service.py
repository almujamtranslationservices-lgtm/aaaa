"""Tests: script service — idea → validated script via providers + fallback."""

from __future__ import annotations

import pytest

from ai_video_factory.ai.llm.demo import DemoLLMProvider
from ai_video_factory.core.exceptions import ProviderNotConfiguredError
from ai_video_factory.models.character import Character
from ai_video_factory.models.scene import SceneStatus
from ai_video_factory.services.script_service import build_chain, generate_script


def test_generate_script_with_demo_provider_arabic():
    script = generate_script(
        idea="قصة اختفاء غامض حدث منذ 100 عام ولم يعرف أحد الحقيقة حتى اليوم.",
        language="ar",
        target_duration=30.0,
        provider_id="demo",
        fallback=False,
    )
    assert script.title
    assert 3 <= script.scene_count <= 40
    assert script.total_duration == pytest.approx(30.0, abs=2.0)
    assert all(scene.narration for scene in script.scenes)
    rich = script.to_rich_scenes()
    assert all(scene.status == SceneStatus.SCRIPTED for scene in rich)


def test_generate_script_with_character_bible():
    hero = Character(name="Omar", age="35", gender="male", hair="short black hair")
    script = generate_script(
        idea="A detective investigates a 100-year-old disappearance.",
        language="en",
        target_duration=25.0,
        characters=[hero],
        provider_id="demo",
        fallback=False,
    )
    assert script.scene_count >= 3


def test_unconfigured_provider_without_fallback_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderNotConfiguredError):
        generate_script(idea="test idea here", provider_id="openai",
                        target_duration=30.0, fallback=False)


def test_generate_script_falls_back_to_demo_when_others_unconfigured(monkeypatch):
    """Selected provider missing its key + nothing else configured → demo saves the run."""
    import ai_video_factory.services.script_service as service

    def fake_create(provider_id, model=None, **kwargs):
        if provider_id == "flaky":
            raise ProviderNotConfiguredError("no key", provider="flaky")
        if provider_id == "demo":
            return DemoLLMProvider()
        raise ProviderNotConfiguredError(f"{provider_id} unconfigured", provider=provider_id)

    monkeypatch.setattr(service, "create_llm_provider", fake_create)
    script = generate_script(
        idea="قصصة اختبار سلسلة الاحتياط", provider_id="flaky",
        target_duration=20.0, fallback=True,
    )
    assert script.scene_count >= 3


def test_build_chain_order_is_free_first(monkeypatch):
    """With every provider configured, the chain follows LOCAL → FREE → PAID."""
    import ai_video_factory.services.script_service as service

    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k2")
    monkeypatch.setenv("OPENAI_API_KEY", "k3")
    created: list[str] = []

    real_create = service.create_llm_provider

    def tracking_create(provider_id, model=None, **kwargs):
        created.append(provider_id)
        if provider_id == "demo":
            return real_create(provider_id)
        # Avoid real network objects: any configured provider → demo double.
        return DemoLLMProvider()

    monkeypatch.setattr(service, "create_llm_provider", tracking_create)
    chain = build_chain("demo")
    assert created[0] == "demo"
    assert created[1:] == ["ollama", "gemini", "openrouter", "openai"]
    assert chain.provider_ids[0] == "demo"
