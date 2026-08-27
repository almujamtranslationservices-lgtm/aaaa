"""Shared async HTTP helpers for ALL provider kinds (httpx).

Centralises error mapping so every provider — LLM, image, video, voice —
converts transport failures to domain errors and never leaks raw exceptions:

* ``httpx`` transport errors      → :class:`ProviderConnectionError`
* HTTP status ≥ 400               → :class:`ProviderResponseError`
* JSON decode failures            → :class:`ProviderResponseError`

An ``http_client`` can be injected (tests use ``httpx.MockTransport``) — an
injected client is never closed by these helpers.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ai_video_factory.core.exceptions import ProviderConnectionError, ProviderResponseError


def _clip(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


async def request_json(
    method: str,
    url: str,
    *,
    provider_id: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 120.0,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Perform one JSON request and return the parsed response body."""
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            response = await client.request(
                method, url, headers=headers, json=payload, params=params,
            )
        except httpx.HTTPError as exc:
            raise ProviderConnectionError(
                f"{provider_id}: connection failed to {url} ({exc})", provider=provider_id,
            ) from exc

        if response.status_code >= 400:
            raise ProviderResponseError(
                f"{provider_id}: HTTP {response.status_code} from {url}: {_clip(response.text)}",
                provider=provider_id,
            )
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderResponseError(
                f"{provider_id}: response was not JSON: {_clip(response.text)}",
                provider=provider_id,
            ) from exc
    finally:
        if http_client is None:
            await client.aclose()


async def request_bytes(
    method: str,
    url: str,
    *,
    provider_id: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 180.0,
    http_client: httpx.AsyncClient | None = None,
) -> bytes:
    """Perform one request expecting binary content (images, audio…)."""
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            response = await client.request(
                method, url, headers=headers, json=payload, data=data, params=params,
            )
        except httpx.HTTPError as exc:
            raise ProviderConnectionError(
                f"{provider_id}: connection failed to {url} ({exc})", provider=provider_id,
            ) from exc
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"{provider_id}: HTTP {response.status_code} from {url}: {_clip(response.text)}",
                provider=provider_id,
            )
        content = response.content
        if not content:
            raise ProviderResponseError(f"{provider_id}: empty binary response from {url}",
                                        provider=provider_id)
        return content
    finally:
        if http_client is None:
            await client.aclose()


def parse_openai_choice(data: dict[str, Any], *, provider_id: str) -> str:
    """Extract assistant text from an OpenAI-compatible response body."""
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderResponseError(
            f"{provider_id}: unexpected response shape: {_clip(json.dumps(data)[:300])}",
            provider=provider_id,
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise ProviderResponseError(f"{provider_id}: empty completion returned", provider=provider_id)
    return content
