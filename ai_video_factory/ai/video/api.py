"""Cloud video provider — Stability AI image-to-video (v2beta, spec §12).

Real public API: ``POST /v2beta/image-to-video`` (multipart: image, seed,
cfg_scale, motion_bucket_id) returns a job ``id``; polling
``GET /v2beta/image-to-video/result/{id}`` answers 202 while rendering and
200 with MP4 bytes when finished.

``motion_strength`` (0-10) maps to ``motion_bucket_id`` (1-255) and camera
motion words bias nothing server-side — they are part of the prompt.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from ai_video_factory.ai.video.base import VideoProvider, VideoRequest
from ai_video_factory.core.exceptions import ProviderResponseError

_POLL_INTERVAL_S = 5.0


class StabilityVideoProvider(VideoProvider):
    """Stability AI Stable Video Diffusion (image-to-video)."""

    id = "stability"
    DEFAULT_MODEL = "stable-video-diffusion"
    DEFAULT_ENDPOINT = "https://api.stability.ai"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.endpoint = (self.endpoint or self.DEFAULT_ENDPOINT).rstrip("/")

    async def generate(self, request: VideoRequest) -> Path:
        if request.output_path is None:
            raise ValueError("StabilityVideoProvider requires request.output_path")
        if not request.image_path.exists():
            raise FileNotFoundError(f"source image missing: {request.image_path}")

        motion = request.motion
        seed = motion.seed if (motion and motion.seed is not None) else 0
        strength = motion.motion_strength if motion else 6.0
        motion_bucket = max(1, min(255, int(strength * 25)))

        client = self._http_client or httpx.AsyncClient(timeout=self.timeout or 600.0)
        try:
            # ---- submit --------------------------------------------------
            try:
                submit = await client.post(
                    f"{self.endpoint}/v2beta/image-to-video",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"image": (request.image_path.name,
                                     request.image_path.read_bytes(), "image/png")},
                    data={"seed": str(seed), "cfg_scale": "1.8",
                          "motion_bucket_id": str(motion_bucket)},
                )
            except httpx.HTTPError as exc:
                raise ProviderResponseError(
                    f"stability: submit failed: {exc}", provider=self.id) from exc
            if submit.status_code >= 400:
                raise ProviderResponseError(
                    f"stability: submit HTTP {submit.status_code}: {submit.text[:200]}",
                    provider=self.id)
            job_id = submit.json().get("id")
            if not job_id:
                raise ProviderResponseError(
                    f"stability: no job id: {submit.text[:200]}", provider=self.id)

            # ---- poll ----------------------------------------------------
            deadline = self.timeout or 600.0
            waited = 0.0
            while True:
                try:
                    result = await client.get(
                        f"{self.endpoint}/v2beta/image-to-video/result/{job_id}",
                        headers={"Authorization": f"Bearer {self.api_key}",
                                 "Accept": "video/*"},
                    )
                except httpx.HTTPError as exc:
                    raise ProviderResponseError(
                        f"stability: poll failed: {exc}", provider=self.id) from exc
                if result.status_code == 202:      # still rendering
                    if waited >= deadline:
                        raise ProviderResponseError(
                            f"stability: job {job_id} timed out", provider=self.id)
                    await asyncio.sleep(_POLL_INTERVAL_S)
                    waited += _POLL_INTERVAL_S
                    continue
                if result.status_code >= 400:
                    raise ProviderResponseError(
                        f"stability: result HTTP {result.status_code}: {result.text[:200]}",
                        provider=self.id)
                content = result.content
                if not content:
                    raise ProviderResponseError("stability: empty video payload",
                                                provider=self.id)
                output = Path(request.output_path)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(content)
                return output
        finally:
            if self._http_client is None:
                await client.aclose()

    async def test_connection(self) -> bool:
        from ai_video_factory.ai.http_common import request_json

        await request_json(
            "GET", f"{self.endpoint}/v1/user/account", provider_id=self.id,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout or 15.0, http_client=self._http_client,
        )
        return True
