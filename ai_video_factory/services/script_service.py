"""Script generation service — idea ➜ validated structured script.

Runs any registered LLM provider (demo works offline) and returns a
schema-validated :class:`Script` (auto-repair applied inside
``Script.from_llm_text``).

Free-first resilience (spec §26): with ``fallback=True`` (default) the
service builds an :class:`LLMChain` — the selected provider first, then every
other *implemented* provider in LOCAL → FREE → PAID order (skipping ones that
are not configured). The offline ``demo`` provider is used as a last resort
only, so a missing API key never blocks the pipeline in DEMO MODE.
"""

from __future__ import annotations

import asyncio
import logging

from ai_video_factory.ai.factory import create_llm_provider
from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.ai.llm.chain import ChainReport, LLMChain
from ai_video_factory.config.providers import ProviderKind, providers_for
from ai_video_factory.core.exceptions import ProviderError
from ai_video_factory.models.character import Character
from ai_video_factory.models.scene import Script
from ai_video_factory.prompts.script_prompt import (
    build_script_system_prompt,
    build_script_user_prompt,
)

logger = logging.getLogger(__name__)


def build_chain(provider_id: str, *, model: str | None = None, fallback: bool = True) -> LLMChain:
    """Instantiate the selected provider + fallbacks (free-first order).

    Raises the first configuration error when no provider could be built.
    """
    providers: list[LLMProvider] = []
    first_error: ProviderError | None = None

    def try_add(candidate_id: str) -> bool:
        nonlocal first_error
        try:
            providers.append(create_llm_provider(
                candidate_id, model=model if candidate_id == provider_id else None,
            ))
            return True
        except ProviderError as exc:
            first_error = first_error or exc
            logger.info("Provider '%s' unavailable for chain (%s)", candidate_id, exc)
            return False

    selected_ok = try_add(provider_id)
    if fallback:
        for info in providers_for(ProviderKind.LLM):
            if not info.implemented or info.id in (provider_id, "demo"):
                continue
            try_add(info.id)
        if not providers and selected_ok is False:
            try_add("demo")  # last resort — keeps DEMO MODE fully functional
    if not providers:
        assert first_error is not None
        raise first_error
    return LLMChain(providers)


def generate_script(
    *,
    idea: str,
    language: str = "ar",
    target_duration: float = 60.0,
    characters: list[Character] | None = None,
    provider_id: str = "demo",
    model: str | None = None,
    scene_count_hint: int | None = None,
    temperature: float = 0.8,
    fallback: bool = True,
) -> Script:
    """Generate and validate a full script for *idea*.

    Raises:
        ProviderError: no provider in the chain is available / all failed.
        JSONRepairError / ScriptValidationError: unusable LLM output.
    """
    chain = build_chain(provider_id, model=model, fallback=fallback)
    system = build_script_system_prompt(
        language=language, target_duration=target_duration, scene_count_hint=scene_count_hint,
    )
    user = build_script_user_prompt(
        idea, characters=characters, target_duration=target_duration,
        scene_count_hint=scene_count_hint, language=language,
    )
    logger.info("Generating script via '%s' (chain=%s, %.0fs, lang=%s)",
                provider_id, "→".join(chain.provider_ids), target_duration, language)
    report = ChainReport()
    text = asyncio.run(chain.generate(
        LLMRequest(system=system, user=user, temperature=temperature), report=report,
    ))
    script = Script.from_llm_text(text)
    logger.info("Script ready via '%s': '%s' — %d scenes, %.1fs total",
                report.provider_id, script.title, script.scene_count, script.total_duration)
    return script
