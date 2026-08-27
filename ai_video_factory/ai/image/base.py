"""Image provider interface — implemented by every image backend (spec §11)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class ImageRequest:
    """One text-to-image request."""

    prompt: str
    negative_prompt: str = ""
    width: int = 1920
    height: int = 1080
    seed: int | None = None
    output_path: Path | None = None       # when None, caller sets it via context
    scene_ref: str | None = None          # e.g. "scene_012" — for logging/cache keys
    style: str | None = None              # optional style prefix (provider-specific)


class ImageProvider(ABC):
    """Base class for all image-generation providers."""

    id: str = "image"

    def __init__(self, *, model: str | None = None, api_key: str | None = None,
                 endpoint: str | None = None, timeout: float | None = None,
                 http_client: httpx.AsyncClient | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        #: Injectable HTTP client (tests pass one backed by MockTransport).
        self._http_client = http_client

    @abstractmethod
    async def generate(self, request: ImageRequest) -> Path:
        """Generate an image and return the path of the saved file."""

    async def test_connection(self) -> bool:
        """Cheap availability probe for the provider settings page."""
        return True  # overridden by networked providers
