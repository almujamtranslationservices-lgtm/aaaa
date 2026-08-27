"""Provider factory — instantiates providers from the registry + environment.

This is the only place that knows how to turn a :class:`ProviderInfo` entry
into a live object. Adding a provider = register it in
``config.providers.PROVIDERS`` and implement its class. Nothing else changes.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import TYPE_CHECKING, Any

from ai_video_factory.config.providers import ProviderInfo, ProviderKind, get_provider_info
from ai_video_factory.core.exceptions import ProviderNotConfiguredError, ProviderNotImplementedError

if TYPE_CHECKING:
    from ai_video_factory.ai.image.base import ImageProvider
    from ai_video_factory.ai.llm.base import LLMProvider
    from ai_video_factory.ai.video.base import VideoProvider
    from ai_video_factory.ai.voice.base import VoiceProvider

logger = logging.getLogger(__name__)


def create_provider(kind: ProviderKind, provider_id: str, **overrides: Any) -> Any:
    """Instantiate one provider by kind + id, wiring keys/endpoints from env."""
    info = get_provider_info(kind, provider_id)

    if not info.implemented:
        raise ProviderNotImplementedError(
            f"Provider '{info.id}' ({kind.value}) is planned for PHASE {info.phase} and not yet available. "
            f"Available {kind.value} providers: demo (and more each phase).",
            provider=info.id,
            planned_phase=info.phase,
        )

    api_key = overrides.pop("api_key", None)
    if api_key is None and info.env_key:
        api_key = os.environ.get(info.env_key) or None
    if info.requires_api_key and not api_key:
        raise ProviderNotConfiguredError(
            f"Provider '{info.id}' requires an API key — set {info.env_key} in your .env file.",
            provider=info.id,
        )

    endpoint = overrides.pop("endpoint", None)
    if endpoint is None:
        if info.endpoint_env and os.environ.get(info.endpoint_env):
            endpoint = os.environ[info.endpoint_env]
        else:
            endpoint = info.default_endpoint

    module = importlib.import_module(info.module)
    provider_class = getattr(module, info.class_name)
    provider = provider_class(api_key=api_key, endpoint=endpoint, **overrides)
    logger.debug("Created %s provider '%s'", kind.value, info.id)
    return provider


def create_llm_provider(provider_id: str, **overrides: Any) -> "LLMProvider":
    from ai_video_factory.ai.llm.base import LLMProvider
    return create_provider(ProviderKind.LLM, provider_id, **overrides)  # type: ignore[return-value]


def create_image_provider(provider_id: str, **overrides: Any) -> "ImageProvider":
    from ai_video_factory.ai.image.base import ImageProvider
    return create_provider(ProviderKind.IMAGE, provider_id, **overrides)  # type: ignore[return-value]


def create_video_provider(provider_id: str, **overrides: Any) -> "VideoProvider":
    from ai_video_factory.ai.video.base import VideoProvider
    return create_provider(ProviderKind.VIDEO, provider_id, **overrides)  # type: ignore[return-value]


def create_voice_provider(provider_id: str, **overrides: Any) -> "VoiceProvider":
    from ai_video_factory.ai.voice.base import VoiceProvider
    return create_provider(ProviderKind.VOICE, provider_id, **overrides)  # type: ignore[return-value]


def provider_status() -> list[ProviderInfo]:
    """All registered providers (for the AI Providers settings page)."""
    from ai_video_factory.config.providers import PROVIDERS

    return list(PROVIDERS)
