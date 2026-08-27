"""Video provider interface — implemented by every i2v backend (spec §12)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import httpx

from ai_video_factory.models.video import MotionParams


@dataclass
class VideoRequest:
    """One image-to-video request."""

    image_path: Path
    prompt: str = ""
    motion: MotionParams | None = None
    width: int = 1920
    height: int = 1080
    output_path: Path | None = None
    scene_ref: str | None = None


class VideoProvider(ABC):
    """Base class for all image-to-video providers."""

    id: str = "video"

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
    async def generate(self, request: VideoRequest) -> Path:
        """Animate the source image and return the path of the saved clip."""

    async def test_connection(self) -> bool:
        """Cheap availability probe for the provider settings page."""
        return True
