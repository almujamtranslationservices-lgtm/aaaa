"""Local image providers — ComfyUI & Stable Diffusion WebUI (spec §11, §25).

Both run on the user's machine: no cost, no keys, full privacy.

* :class:`ComfyUIImageProvider` — queues an API-format workflow on
  ``POST /prompt``, polls ``GET /history/{id}`` and downloads the resulting
  image from ``GET /view``. The checkpoint is configurable via the provider
  *model* override or ``COMFYUI_CHECKPOINT``.
* :class:`SDWebUIImageProvider` — AUTOMATIC1111 ``POST /sdapi/v1/txt2img``
  returning base64 PNGs.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from ai_video_factory.ai.http_common import request_bytes, request_json
from ai_video_factory.ai.image.base import ImageProvider, ImageRequest
from ai_video_factory.core.exceptions import ProviderResponseError


class ComfyUIImageProvider(ImageProvider):
    """ComfyUI local image generation (workflow API)."""

    id = "comfyui"
    DEFAULT_MODEL = ""  # checkpoint name resolved from env COMFYUI_CHECKPOINT
    DEFAULT_ENDPOINT = "http://localhost:8188"
    POLL_INTERVAL_S = 1.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = self.model or os.environ.get("COMFYUI_CHECKPOINT") or "sd_xl_base_1.0.safetensors"
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")
        self.client_id = uuid.uuid4().hex

    # ------------------------------------------------------------- workflow
    def _build_workflow(self, request: ImageRequest, seed: int) -> dict[str, Any]:
        """Standard txt2img API workflow with the request values injected."""
        return {
            "3": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": 30, "cfg": 7.0, "sampler_name": "dpmpp_2m",
                "scheduler": "karras", "denoise": 1.0,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["5", 0],
            }},
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self.model}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {
                "width": request.width, "height": request.height, "batch_size": 1,
            }},
            "6": {"class_type": "CLIPTextEncode", "inputs": {
                "text": request.prompt, "clip": ["4", 1],
            }},
            "7": {"class_type": "CLIPTextEncode", "inputs": {
                "text": request.negative_prompt or "watermark, text, deformed",
                "clip": ["4", 1],
            }},
            "8": {"class_type": "VAEDecode", "inputs": {
                "samples": ["3", 0], "vae": ["4", 2],
            }},
            "9": {"class_type": "SaveImage", "inputs": {
                "filename_prefix": f"avf_{request.scene_ref or 'image'}", "images": ["8", 0],
            }},
        }

    # -------------------------------------------------------------- generate
    async def generate(self, request: ImageRequest) -> Path:
        if request.output_path is None:
            raise ValueError("ComfyUIImageProvider requires request.output_path")
        seed = request.seed if request.seed is not None else 0
        queued = await request_json(
            "POST", f"{self.endpoint}/prompt", provider_id=self.id,
            payload={"prompt": self._build_workflow(request, seed), "client_id": self.client_id},
            timeout=self.timeout or 60.0, http_client=self._http_client,
        )
        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise ProviderResponseError(
                f"comfyui: no prompt_id in queue response: {str(queued)[:200]}", provider=self.id)

        outputs = await self._wait_for_history(prompt_id)
        image_meta = self._first_image_entry(outputs)

        content = await request_bytes(
            "GET", f"{self.endpoint}/view", provider_id=self.id,
            params={"filename": image_meta["filename"],
                    "subfolder": image_meta.get("subfolder", ""),
                    "type": image_meta.get("type", "output")},
            timeout=self.timeout or 120.0, http_client=self._http_client,
        )
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return output

    async def _wait_for_history(self, prompt_id: str) -> dict[str, Any]:
        deadline = (self.timeout or 300.0)
        waited = 0.0
        while waited < deadline:
            history = await request_json(
                "GET", f"{self.endpoint}/history/{prompt_id}", provider_id=self.id,
                timeout=30.0, http_client=self._http_client,
            )
            entry = history.get(prompt_id)
            if entry and entry.get("outputs"):
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ProviderResponseError(
                        f"comfyui: workflow executed with error: {str(status)[:300]}",
                        provider=self.id)
                return entry["outputs"]
            await asyncio.sleep(self.POLL_INTERVAL_S)
            waited += self.POLL_INTERVAL_S
        raise ProviderResponseError(f"comfyui: timed out waiting for job {prompt_id}",
                                    provider=self.id)

    @staticmethod
    def _first_image_entry(outputs: dict[str, Any]) -> dict[str, Any]:
        for node_output in outputs.values():
            images = node_output.get("images") or []
            if images:
                return images[0]
        raise ProviderResponseError("comfyui: workflow produced no images", provider="comfyui")

    async def test_connection(self) -> bool:
        await request_json(
            "GET", f"{self.endpoint}/system_stats", provider_id=self.id,
            timeout=self.timeout or 10.0, http_client=self._http_client,
        )
        return True


class SDWebUIImageProvider(ImageProvider):
    """AUTOMATIC1111 Stable Diffusion WebUI (``--api``) image generation."""

    id = "sd_webui"
    DEFAULT_ENDPOINT = "http://localhost:7860"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    async def generate(self, request: ImageRequest) -> Path:
        if request.output_path is None:
            raise ValueError("SDWebUIImageProvider requires request.output_path")
        data = await request_json(
            "POST", f"{self.endpoint}/sdapi/v1/txt2img", provider_id=self.id,
            payload={
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt or "",
                "width": request.width, "height": request.height,
                "seed": request.seed if request.seed is not None else -1,
                "steps": 30, "cfg_scale": 7.0,
                "sampler_name": "DPM++ 2M",
            },
            timeout=self.timeout or 300.0, http_client=self._http_client,
        )
        images_b64 = data.get("images") or []
        if not images_b64:
            raise ProviderResponseError(
                f"sd_webui: no images in response: {str(data)[:200]}", provider=self.id)
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(base64.b64decode(images_b64[0]))
        return output

    async def test_connection(self) -> bool:
        await request_json(
            "GET", f"{self.endpoint}/sdapi/v1/options", provider_id=self.id,
            timeout=self.timeout or 10.0, http_client=self._http_client,
        )
        return True
