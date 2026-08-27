"""Tests: real LLM providers against a mock HTTP server (no network, no keys).

Covers request shape, response parsing, error mapping, connection tests,
model resolution (explicit → env → default) and the fallback chain.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ai_video_factory.ai.factory import create_llm_provider
from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.ai.llm.chain import ChainReport, LLMChain
from ai_video_factory.ai.llm.demo import DemoLLMProvider
from ai_video_factory.ai.llm.gemini import GeminiProvider
from ai_video_factory.ai.llm.ollama import OllamaProvider
from ai_video_factory.ai.llm.openai import OpenAIProvider
from ai_video_factory.ai.llm.openrouter import OpenRouterProvider
from ai_video_factory.core.exceptions import (
    ProviderConnectionError, ProviderNotConfiguredError, ProviderResponseError,
)

REQUEST = LLMRequest(system="sys", user="usr", max_tokens=64, temperature=0.5)


def _client(handler, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)


def _ok_openai_body(text: str = "hello") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


# ---------------------------------------------------------------------- ollama
def test_ollama_generate_parses_content_and_shape():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": "  نص الجواب  "},
            "done": True,
        })

    provider = OllamaProvider(endpoint="http://testserver", model="llama3.1",
                              http_client=_client(handler))
    text = asyncio.run(provider.generate(REQUEST))
    assert text == "  نص الجواب  "
    assert captured["url"].endswith("/api/chat")
    payload = captured["payload"]
    assert payload["model"] == "llama3.1"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.5
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]


def test_ollama_error_payload_and_empty_completion():
    provider = OllamaProvider(endpoint="http://testserver", http_client=_client(
        lambda request: httpx.Response(200, json={"error": "model not found"})))
    with pytest.raises(ProviderResponseError, match="model not found"):
        asyncio.run(provider.generate(REQUEST))

    empty = OllamaProvider(endpoint="http://testserver", http_client=_client(
        lambda request: httpx.Response(200, json={"message": {"content": ""}})))
    with pytest.raises(ProviderResponseError, match="empty"):
        asyncio.run(empty.generate(REQUEST))


def test_ollama_test_connection_checks_model_installed():
    ok = OllamaProvider(endpoint="http://testserver", model="llama3.1", http_client=_client(
        lambda request: httpx.Response(200, json={"models": [{"name": "llama3.1:latest"}]})))
    assert asyncio.run(ok.test_connection()) is True

    missing = OllamaProvider(endpoint="http://testserver", model="mistral", http_client=_client(
        lambda request: httpx.Response(200, json={"models": [{"name": "llama3.1:latest"}]})))
    with pytest.raises(ProviderResponseError, match="ollama pull"):
        asyncio.run(missing.test_connection())


# ---------------------------------------------------------------------- gemini
def test_gemini_generate_uses_header_key_and_parses_parts():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("x-goog-api-key")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "part one "}, {"text": "part two"}]}}],
        })

    provider = GeminiProvider(api_key="gk-123", model="gemini-2.0-flash",
                              http_client=_client(handler))
    text = asyncio.run(provider.generate(REQUEST))
    assert text == "part one part two"
    assert "key=" not in captured["url"]                      # key never in URL
    assert captured["auth"] == "gk-123"                       # key via header
    assert ":generateContent" in captured["url"]
    assert captured["payload"]["generationConfig"]["maxOutputTokens"] == 64


def test_gemini_blocked_prompt_maps_to_response_error():
    provider = GeminiProvider(api_key="gk-1", http_client=_client(
        lambda request: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})))
    with pytest.raises(ProviderResponseError, match="SAFETY"):
        asyncio.run(provider.generate(REQUEST))


# ------------------------------------------------------- openai / openrouter
def test_openai_generate_and_headers():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_openai_body("openai says hi"))

    provider = OpenAIProvider(api_key="sk-test", http_client=_client(handler))
    assert asyncio.run(provider.generate(REQUEST)) == "openai says hi"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["payload"]["max_tokens"] == 64


def test_openrouter_generate_uses_free_default_model():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_openai_body("or ok"))

    provider = OpenRouterProvider(api_key="or-key", http_client=_client(handler))
    assert asyncio.run(provider.generate(REQUEST)) == "or ok"
    assert captured["payload"]["model"] == OpenRouterProvider.DEFAULT_MODEL
    assert "free" in provider.model


def test_openai_compatible_bad_shape_raises():
    provider = OpenAIProvider(api_key="sk-x", http_client=_client(
        lambda request: httpx.Response(200, json={"unexpected": True})))
    with pytest.raises(ProviderResponseError, match="unexpected response shape"):
        asyncio.run(provider.generate(REQUEST))


# --------------------------------------------------------------- error mapping
def test_http_error_status_maps_to_response_error():
    provider = OpenAIProvider(api_key="sk-x", http_client=_client(
        lambda request: httpx.Response(401, text="unauthorized")))
    with pytest.raises(ProviderResponseError, match="HTTP 401"):
        asyncio.run(provider.generate(REQUEST))


def test_transport_failure_maps_to_connection_error():
    def refusing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OllamaProvider(endpoint="http://testserver", http_client=_client(refusing_handler))
    with pytest.raises(ProviderConnectionError):
        asyncio.run(provider.generate(REQUEST))


# ------------------------------------------------------- model & configuration
def test_model_resolution_explicit_env_default(monkeypatch):
    explicit = OpenAIProvider(api_key="k", model="gpt-4o")
    assert explicit.model == "gpt-4o"

    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    from_env = OpenAIProvider(api_key="k")
    assert from_env.model == "gpt-4.1-mini"

    monkeypatch.delenv("OPENAI_MODEL")
    assert OpenAIProvider(api_key="k").model == OpenAIProvider.DEFAULT_MODEL


def test_factory_requires_api_key_when_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderNotConfiguredError, match="OPENAI_API_KEY"):
        create_llm_provider("openai")


def test_factory_builds_configured_providers(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk-factory")
    provider = create_llm_provider("gemini")
    assert isinstance(provider, GeminiProvider)
    assert provider.api_key == "gk-factory"


# ---------------------------------------------------------------------- chain
class _Scripted(LLMProvider):
    """Test double returning canned text or raising."""

    def __init__(self, provider_id: str, *, text: str | None = None,
                 error: Exception | None = None) -> None:
        super().__init__()
        self.id = provider_id
        self._text = text
        self._error = error

    async def generate(self, request: LLMRequest) -> str:
        if self._error:
            raise self._error
        assert self._text is not None
        return self._text


def test_chain_returns_first_success():
    chain = LLMChain([
        _Scripted("a", error=ProviderConnectionError("down", provider="a")),
        _Scripted("b", text='{"ok": true}'),
        _Scripted("c", text="never reached"),
    ])
    report = ChainReport()
    text = asyncio.run(chain.generate(REQUEST, report=report))
    assert text == '{"ok": true}'
    assert report.provider_id == "b"
    assert report.fell_back and report.attempts[0][0] == "a"


def test_chain_raises_last_error_when_all_fail():
    chain = LLMChain([
        _Scripted("a", error=ProviderConnectionError("a down", provider="a")),
        _Scripted("b", error=ProviderResponseError("b bad", provider="b")),
    ])
    with pytest.raises(ProviderResponseError, match="b bad"):
        asyncio.run(chain.generate(REQUEST))


def test_chain_generate_json_applies_repair():
    chain = LLMChain([_Scripted("a", text="```json\n{'x': 1,}\n```")])
    assert asyncio.run(chain.generate_json(REQUEST)) == {"x": 1}


def test_chain_needs_providers():
    with pytest.raises(ValueError):
        LLMChain([])


def test_real_providers_can_chain_with_demo_fallback():
    """Demo provider still works inside a chain (offline resilience)."""
    chain = LLMChain([
        _Scripted("broken", error=ProviderConnectionError("offline", provider="broken")),
        DemoLLMProvider(),
    ])
    report = ChainReport()
    text = asyncio.run(chain.generate(
        LLMRequest(system="s", user="VIDEO IDEA:\ntest idea\n\nLANGUAGE: ar\nTARGET DURATION (seconds): 20\nSCENES: 4"),
        report=report,
    ))
    assert report.provider_id == "demo"
    assert json.loads(text)["title"]
