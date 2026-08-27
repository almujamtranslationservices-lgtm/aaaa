"""Static registry of AI providers (no secrets — keys stay in ``.env``).

Free-first architecture
-----------------------
Providers are ordered LOCAL → FREE → PAID inside every capability, and the UI
/ settings expose this ordering as the default fallback chain. Adding a new
provider means appending one :class:`ProviderInfo` entry (plus implementing
its class) — nothing else in the system needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderKind(str, Enum):
    LLM = "llm"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"


class ProviderTier(str, Enum):
    LOCAL = "local"  # runs on the user's machine (Ollama, ComfyUI, Piper…)
    FREE = "free"    # free cloud APIs (Edge TTS, Gemini free tier…)
    PAID = "paid"    # paid cloud APIs


TIER_ORDER = {ProviderTier.LOCAL: 0, ProviderTier.FREE: 1, ProviderTier.PAID: 2}


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata about one provider implementation."""

    id: str
    name: str
    kind: ProviderKind
    tier: ProviderTier
    module: str                 # dotted import path of the provider class
    class_name: str
    env_key: str | None = None      # env var holding the API key (if any)
    endpoint_env: str | None = None # env var holding a custom base URL
    default_endpoint: str | None = None
    requires_api_key: bool = False
    implemented: bool = False   # honest flag — False until the phase lands
    phase: int | None = None    # delivery phase in which it becomes available


# fmt: off
PROVIDERS: tuple[ProviderInfo, ...] = (
    # ---------------- LLM ----------------
    ProviderInfo("demo", "Demo (offline mock)", ProviderKind.LLM, ProviderTier.LOCAL,
                 "ai_video_factory.ai.llm.demo", "DemoLLMProvider", implemented=True, phase=1),
    ProviderInfo("ollama", "Ollama (local models)", ProviderKind.LLM, ProviderTier.LOCAL,
                 "ai_video_factory.ai.llm.ollama", "OllamaProvider",
                 endpoint_env="OLLAMA_BASE_URL", default_endpoint="http://localhost:11434",
                 implemented=True, phase=5),
    ProviderInfo("gemini", "Google Gemini (free tier)", ProviderKind.LLM, ProviderTier.FREE,
                 "ai_video_factory.ai.llm.gemini", "GeminiProvider",
                 env_key="GEMINI_API_KEY", requires_api_key=True, implemented=True, phase=5),
    ProviderInfo("openrouter", "OpenRouter (free models available)", ProviderKind.LLM, ProviderTier.FREE,
                 "ai_video_factory.ai.llm.openrouter", "OpenRouterProvider",
                 env_key="OPENROUTER_API_KEY", requires_api_key=True, implemented=True, phase=5),
    ProviderInfo("openai", "OpenAI", ProviderKind.LLM, ProviderTier.PAID,
                 "ai_video_factory.ai.llm.openai", "OpenAIProvider",
                 env_key="OPENAI_API_KEY", requires_api_key=True, implemented=True, phase=5),

    # ---------------- IMAGE ----------------
    ProviderInfo("demo", "Demo (Pillow placeholder art)", ProviderKind.IMAGE, ProviderTier.LOCAL,
                 "ai_video_factory.ai.image.demo", "DemoImageProvider", implemented=True, phase=7),
    ProviderInfo("comfyui", "ComfyUI (local)", ProviderKind.IMAGE, ProviderTier.LOCAL,
                 "ai_video_factory.ai.image.local", "ComfyUIImageProvider",
                 endpoint_env="COMFYUI_BASE_URL", default_endpoint="http://localhost:8188",
                 implemented=True, phase=7),
    ProviderInfo("sd_webui", "Stable Diffusion WebUI (local)", ProviderKind.IMAGE, ProviderTier.LOCAL,
                 "ai_video_factory.ai.image.local", "SDWebUIImageProvider",
                 endpoint_env="SD_WEBUI_BASE_URL", default_endpoint="http://localhost:7860",
                 implemented=True, phase=7),
    ProviderInfo("huggingface", "Hugging Face Inference API", ProviderKind.IMAGE, ProviderTier.FREE,
                 "ai_video_factory.ai.image.api", "HuggingFaceImageProvider",
                 env_key="HUGGINGFACE_API_KEY", requires_api_key=True, implemented=True, phase=7),
    ProviderInfo("stability", "Stability AI", ProviderKind.IMAGE, ProviderTier.PAID,
                 "ai_video_factory.ai.image.api", "StabilityImageProvider",
                 env_key="STABILITY_API_KEY", requires_api_key=True, implemented=True, phase=7),
    ProviderInfo("openai", "OpenAI Images", ProviderKind.IMAGE, ProviderTier.PAID,
                 "ai_video_factory.ai.image.api", "OpenAIImageProvider",
                 env_key="OPENAI_API_KEY", requires_api_key=True, implemented=True, phase=7),

    # ---------------- VIDEO (image-to-video) ----------------
    ProviderInfo("demo", "Demo (Ken Burns via FFmpeg)", ProviderKind.VIDEO, ProviderTier.LOCAL,
                 "ai_video_factory.ai.video.demo", "DemoVideoProvider", implemented=True, phase=8),
    ProviderInfo("comfyui", "ComfyUI (AnimateDiff / SVD, local)", ProviderKind.VIDEO, ProviderTier.LOCAL,
                 "ai_video_factory.ai.video.local", "ComfyUIVideoProvider",
                 endpoint_env="COMFYUI_BASE_URL", default_endpoint="http://localhost:8188",
                 implemented=True, phase=8),
    ProviderInfo("stability", "Stability AI (Stable Video Diffusion)", ProviderKind.VIDEO, ProviderTier.PAID,
                 "ai_video_factory.ai.video.api", "StabilityVideoProvider",
                 env_key="STABILITY_API_KEY", requires_api_key=True, implemented=True, phase=8),

    # ---------------- VOICE ----------------
    ProviderInfo("demo", "Demo (speech-like tones, offline)", ProviderKind.VOICE, ProviderTier.LOCAL,
                 "ai_video_factory.ai.voice.demo", "DemoVoiceProvider", implemented=True, phase=9),
    ProviderInfo("edge", "Microsoft Edge TTS (free)", ProviderKind.VOICE, ProviderTier.FREE,
                 "ai_video_factory.ai.voice.edge_tts", "EdgeTTSProvider", implemented=True, phase=9),
    ProviderInfo("piper", "Piper (local TTS)", ProviderKind.VOICE, ProviderTier.LOCAL,
                 "ai_video_factory.ai.voice.local", "PiperLocalProvider",
                 endpoint_env="LOCAL_TTS_BASE_URL", default_endpoint="http://localhost:5000",
                 implemented=True, phase=9),
    ProviderInfo("elevenlabs", "ElevenLabs", ProviderKind.VOICE, ProviderTier.PAID,
                 "ai_video_factory.ai.voice.elevenlabs", "ElevenLabsProvider",
                 env_key="ELEVENLABS_API_KEY", requires_api_key=True, implemented=True, phase=9),
)
# fmt: on


def providers_for(kind: ProviderKind) -> list[ProviderInfo]:
    """Return all providers of *kind*, free-first (LOCAL → FREE → PAID)."""
    entries = [info for info in PROVIDERS if info.kind == kind]
    return sorted(entries, key=lambda info: TIER_ORDER[info.tier])


def default_chain(kind: ProviderKind) -> list[str]:
    """Free-first fallback chain of provider ids for *kind*."""
    return [info.id for info in providers_for(kind)]


def get_provider_info(kind: ProviderKind, provider_id: str) -> ProviderInfo:
    """Look up one provider or raise ``KeyError`` with a helpful message."""
    for info in PROVIDERS:
        if info.kind == kind and info.id == provider_id:
            return info
    known = ", ".join(info.id for info in providers_for(kind))
    raise KeyError(f"Unknown {kind.value} provider '{provider_id}'. Known: {known}")
