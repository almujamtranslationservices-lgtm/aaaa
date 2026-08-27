"""Local video provider — ComfyUI image-to-video (spec §12, §25).

Template-based: the API-format workflow in
``assets/templates/comfyui_i2v_template.json`` is a documented starting point
that users adapt to their own ComfyUI install (AnimateDiff / SVD chains and a
video saver node like ``VHS_VideoCombine``). Placeholders are substituted at
submit time; a custom template can be selected via ``COMFYUI_I2V_TEMPLATE``.

Flow: upload the source image (``POST /upload/image``) → queue the workflow
(``POST /prompt``) → poll ``GET /history/{id}`` → download the clip from
``GET /view``.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from ai_video_factory.ai.http_common import request_bytes, request_json
from ai_video_factory.ai.video.base import VideoProvider, VideoRequest
from ai_video_factory.config.settings import project_root
from ai_video_factory.core.exceptions import ProviderError, ProviderResponseError

DEFAULT_TEMPLATE = project_root() / "assets" / "templates" / "comfyui_i2v_template.json"

_PLACEHOLDERS = ("{IMAGE_NAME}", "{PROMPT}", "{NEGATIVE_PROMPT}", "{SEED}",
                 "{WIDTH}", "{HEIGHT}", "{FRAMES}", "{FPS}")

_OUTPUT_KEYS = ("gifs", "videos", "images")  # VHS writes 'gifs'; other savers differ


class ComfyUIVideoProvider(VideoProvider):
    """ComfyUI local image-to-video (user-adaptable workflow template)."""

    id = "comfyui"
    DEFAULT_ENDPOINT = "http://localhost:8188"
    POLL_INTERVAL_S = 2.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")
        self.client_id = uuid.uuid4().hex
        template = os.environ.get("COMFYUI_I2V_TEMPLATE") or str(DEFAULT_TEMPLATE)
        try:
            parsed = json.loads(Path(template).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderError(
                f"comfyui: cannot read i2v workflow template '{template}': {exc}",
                provider="comfyui",
            ) from exc
        # Documentation keys ("_readme") are stripped — only nodes are submitted.
        self._template: dict[str, Any] = {
            key: value for key, value in parsed.items() if not key.startswith("_")
        }

    # --------------------------------------------------------------- helpers
    def _build_workflow(self, request: VideoRequest, image_name: str, seed: int) -> dict[str, Any]:
        """Deep-copy the template, replacing placeholders with TYPED values.

        Numbers (seed/width/height/frames/fps) are injected as ints so the
        workflow stays valid for the ComfyUI API.
        """
        motion = request.motion
        duration = motion.duration_s if motion else 4.0
        fps = motion.fps if motion else 24
        frames = max(2, int(round(duration * fps)))

        substitutions: dict[str, Any] = {
            "{IMAGE_NAME}": image_name,
            "{PROMPT}": request.prompt or "cinematic motion",
            "{NEGATIVE_PROMPT}": "blurry, distorted, watermark",
            "{SEED}": int(seed),
            "{WIDTH}": int(request.width),
            "{HEIGHT}": int(request.height),
            "{FRAMES}": int(frames),
            "{FPS}": int(fps),
        }

        def replace(node: Any) -> Any:
            if isinstance(node, str):
                return substitutions.get(node, node)
            if isinstance(node, list):
                return [replace(item) for item in node]
            if isinstance(node, dict):
                return {key: replace(value) for key, value in node.items()}
            return node

        return replace(copy.deepcopy(self._template))

    async def _upload_image(self, image_path: Path) -> str:
        """Upload the still; return the server-side filename."""
        client = self._http_client or httpx.AsyncClient(timeout=self.timeout or 120.0)
        try:
            try:
                response = await client.post(
                    f"{self.endpoint}/upload/image",
                    files={"image": (image_path.name, image_path.read_bytes(), "image/png")},
                    data={"overwrite": "true", "client_id": self.client_id},
                )
            except httpx.HTTPError as exc:
                raise ProviderResponseError(
                    f"comfyui: image upload failed: {exc}", provider=self.id) from exc
            if response.status_code >= 400:
                raise ProviderResponseError(
                    f"comfyui: upload HTTP {response.status_code}: {response.text[:200]}",
                    provider=self.id)
            data = response.json()
            name = data.get("name")
            if not name:
                raise ProviderResponseError(
                    f"comfyui: upload returned no name: {str(data)[:200]}", provider=self.id)
            return name
        finally:
            if self._http_client is None:
                await client.aclose()

    async def _wait_for_history(self, prompt_id: str) -> dict[str, Any]:
        deadline = self.timeout or 600.0
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
                        f"comfyui: i2v workflow error: {str(status)[:300]}", provider=self.id)
                return entry["outputs"]
            await asyncio.sleep(self.POLL_INTERVAL_S)
            waited += self.POLL_INTERVAL_S
        raise ProviderResponseError(f"comfyui: i2v job {prompt_id} timed out", provider=self.id)

    @staticmethod
    def _find_clip(outputs: dict[str, Any]) -> dict[str, Any]:
        for node_output in outputs.values():
            for key in _OUTPUT_KEYS:
                items = node_output.get(key) or []
                if items:
                    return items[0]
        raise ProviderResponseError("comfyui: i2v workflow produced no video", provider="comfyui")

    # -------------------------------------------------------------- generate
    async def generate(self, request: VideoRequest) -> Path:
        if request.output_path is None:
            raise ValueError("ComfyUIVideoProvider requires request.output_path")
        if not request.image_path.exists():
            raise FileNotFoundError(f"source image missing: {request.image_path}")

        seed = request.motion.seed if (request.motion and request.motion.seed) else 0
        image_name = await self._upload_image(request.image_path)
        workflow = self._build_workflow(request, image_name, seed)
        queued = await request_json(
            "POST", f"{self.endpoint}/prompt", provider_id=self.id,
            payload={"prompt": workflow, "client_id": self.client_id},
            timeout=self.timeout or 60.0, http_client=self._http_client,
        )
        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise ProviderResponseError(
                f"comfyui: no prompt_id: {str(queued)[:200]}", provider=self.id)

        outputs = await self._wait_for_history(prompt_id)
        clip = self._find_clip(outputs)
        content = await request_bytes(
            "GET", f"{self.endpoint}/view", provider_id=self.id,
            params={"filename": clip["filename"],
                    "subfolder": clip.get("subfolder", ""),
                    "type": clip.get("type", "output")},
            timeout=self.timeout or 180.0, http_client=self._http_client,
        )
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return output

    async def test_connection(self) -> bool:
        await request_json(
            "GET", f"{self.endpoint}/system_stats", provider_id=self.id,
            timeout=self.timeout or 10.0, http_client=self._http_client,
        )
        return True
