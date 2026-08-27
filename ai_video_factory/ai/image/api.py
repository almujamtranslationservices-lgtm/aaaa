"""Cloud image providers — Hugging Face, Stability AI and OpenAI (spec §11).

* :class:`HuggingFaceImageProvider` — Inference API ``models/{model}`` with
  JSON in / raw image bytes out. Free tier available.
* :class:`StabilityImageProvider` — v2beta ``stable-image/generate/{engine}``
  multipart form, raw image bytes out.
* :class:`OpenAIImageProvider` — ``images/generations`` with ``b64_json``.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from ai_video_factory.ai.http_common import request_bytes, request_json
from ai_video_factory.ai.image.base import ImageProvider, ImageRequest
from ai_video_factory.core.exceptions import ProviderResponseError

_OPENAI_SIZES = {(16, 9): "1536x1024", (9, 16): "1024x1536", (1, 1): "1024x1024"}


def _aspect_key(width: int, height: int) -> tuple[int, int]:
    if width > height:
        return (16, 9)
    if height > width:
        return (9, 16)
    return (1, 1)


class HuggingFaceImageProvider(ImageProvider):
    """Hugging Face Inference API (free tier available)."""

    id = "huggingface"
    DEFAULT_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
    DEFAULT_ENDPOINT = "https://api-inference.huggingface.co"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("HUGGINGFACE_IMAGE_MODEL") or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    async def generate(self, request: ImageRequest) -> Path:
        if request.output_path is None:
            raise ValueError("HuggingFaceImageProvider requires request.output_path")
        content = await request_bytes(
            "POST", f"{self.endpoint}/models/{self.model}", provider_id=self.id,
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload={
                "inputs": request.prompt,
                "parameters": {
                    "negative_prompt": request.negative_prompt or None,
                    "width": request.width, "height": request.height,
                    "seed": request.seed if request.seed is not None else None,
                },
            },
            timeout=self.timeout or 180.0, http_client=self._http_client,
        )
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return output

    async def test_connection(self) -> bool:
        await request_json(
            "GET", f"{self.endpoint}/whoami/v2", provider_id=self.id,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout or 15.0, http_client=self._http_client,
        )
        return True


class StabilityImageProvider(ImageProvider):
    """Stability AI v2beta stable-image generation."""

    id = "stability"
    DEFAULT_MODEL = "core"   # engine: core | ultra
    DEFAULT_ENDPOINT = "https://api.stability.ai"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("STABILITY_IMAGE_MODEL") or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    async def generate(self, request: ImageRequest) -> Path:
        if request.output_path is None:
            raise ValueError("StabilityImageProvider requires request.output_path")
        width, height = request.width, request.height
        content = await request_bytes(
            "POST", f"{self.endpoint}/v2beta/stable-image/generate/{self.model}",
            provider_id=self.id,
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "image/*"},
            data={
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt or "",
                "output_format": "png",
                "aspect_ratio": f"{width}:{height}" if (width, height) in
                {(1024, 1024), (1152, 896), (896, 1152), (1216, 832), (832, 1216),
                 (1344, 768), (768, 1344), (1536, 640), (640, 1536)} else "1:1",
                **({"seed": str(request.seed)} if request.seed is not None else {}),
            },
            timeout=self.timeout or 180.0, http_client=self._http_client,
        )
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return output

    async def test_connection(self) -> bool:
        await request_json(
            "GET", f"{self.endpoint}/v1/user/account", provider_id=self.id,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout or 15.0, http_client=self._http_client,
        )
        return True


class OpenAIImageProvider(ImageProvider):
    """OpenAI Images API (``gpt-image-1`` default, b64_json responses)."""

    id = "openai"
    DEFAULT_MODEL = "gpt-image-1"
    DEFAULT_ENDPOINT = "https://api.openai.com/v1"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("OPENAI_IMAGE_MODEL") or self.DEFAULT_MODEL
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    def _size_for(self, width: int, height: int) -> str:
        if self.model.startswith("dall-e-3"):
            return _OPENAI_SIZES.get(_aspect_key(width, height), "1024x1024")
        return _OPENAI_SIZES.get(_aspect_key(width, height), "1024x1024")

    async def generate(self, request: ImageRequest) -> Path:
        if request.output_path is None:
            raise ValueError("OpenAIImageProvider requires request.output_path")
        data = await request_json(
            "POST", f"{self.endpoint}/images/generations", provider_id=self.id,
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload={
                "model": self.model,
                "prompt": (f"{request.prompt}\n\nAvoid any text or watermarks in the image."
                           if request.negative_prompt else request.prompt),
                "size": self._size_for(request.width, request.height),
                "n": 1,
                **({"response_format": "b64_json"}
                   if not self.model.startswith("gpt-image") else {}),
            },
            timeout=self.timeout or 240.0, http_client=self._http_client,
        )
        items = data.get("data") or []
        if not items or not items[0].get("b64_json"):
            raise ProviderResponseError(
                f"openai: no b64 image in response: {str(data)[:200]}", provider=self.id)
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(base64.b64decode(items[0]["b64_json"]))
        return output

    async def test_connection(self) -> bool:
        await request_json(
            "GET", f"{self.endpoint}/models", provider_id=self.id,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout or 15.0, http_client=self._http_client,
        )
        return True
