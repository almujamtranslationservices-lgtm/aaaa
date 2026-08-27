"""LLM fallback chain — free-first resilience (spec §26).

A chain tries providers in order (LOCAL → FREE → PAID, as registered) and
returns the first successful completion. Failures are logged; if every
provider fails, the last error is raised. This is the mechanism behind
``Ollama → Gemini → OpenRouter → …`` transparent fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.core.exceptions import ProviderError
from ai_video_factory.utils.validation import parse_llm_json

logger = logging.getLogger(__name__)


@dataclass
class ChainReport:
    """Outcome of one chain run (for logs, UI and tests)."""

    provider_id: str | None = None
    attempts: list[tuple[str, str]] = field(default_factory=list)  # (provider_id, error)

    @property
    def fell_back(self) -> bool:
        """True when at least one provider failed before the successful one."""
        return bool(self.attempts)


class LLMChain:
    """Ordered list of providers with automatic fallback."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("LLMChain needs at least one provider")
        self._providers = list(providers)

    @property
    def provider_ids(self) -> list[str]:
        return [provider.id for provider in self._providers]

    async def generate(self, request: LLMRequest, *, report: ChainReport | None = None) -> str:
        """Return the first successful raw completion across the chain."""
        report = report or ChainReport()
        last_error: ProviderError | None = None
        for provider in self._providers:
            try:
                text = await provider.generate(request)
                report.provider_id = provider.id
                if report.attempts:
                    logger.info("LLM chain fell back to '%s' after: %s",
                                provider.id, "; ".join(f"{p}:{e}" for p, e in report.attempts))
                return text
            except ProviderError as exc:
                last_error = exc
                report.attempts.append((provider.id, str(exc)[:200]))
                logger.warning("LLM provider '%s' failed, trying next: %s", provider.id, exc)
        assert last_error is not None
        raise last_error

    async def generate_json(self, request: LLMRequest, *, report: ChainReport | None = None) -> dict:
        """First successful completion parsed as JSON (auto-repair applied)."""
        text = await self.generate(request, report=report)
        return parse_llm_json(text)
