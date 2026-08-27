"""Tests: image providers — demo art, mock HTTP providers, error mapping."""

from __future__ import annotations

import asyncio
import base64
import io
import json

import httpx
import pytest
from PIL import Image

from ai_video_factory.ai.factory import create_image_provider
from ai_video_factory.ai.image.base import ImageRequest
from ai_video_factory.ai.image.demo import DemoImageProvider
from ai_video_factory.ai.image.local import ComfyUIImageProvider, SDWebUIImageProvider
from ai_video_factory.core.exceptions import (
    ProviderConnectionError, ProviderNotConfiguredError, ProviderResponseError,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")


def _read_png(path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


# ------------------------------------------------------------------------ demo
def test_demo_image_provider_creates_real_png_with_exact_dims(tmp_path):
    provider = DemoImageProvider()
    out = tmp_path / "scene_001" / "image.png"
    request = ImageRequest(prompt="a foggy hill", width=640, height=360, seed=7,
                           output_path=out, scene_ref="scene_001")
    saved = asyncio.run(provider.generate(request))
    assert saved == out and out.exists()
    assert _read_png(out) == (640, 360)


def test_demo_image_provider_deterministic_per_seed(tmp_path):
    provider = DemoImageProvider()
    first, second, third = (tmp_path / f"{name}.png" for name in ("a", "b", "c"))
    asyncio.run(provider.generate(ImageRequest(prompt="p", width=320, height=180, seed=42, output_path=first)))
    asyncio.run(provider.generate(ImageRequest(prompt="p", width=320, height=180, seed=42, output_path=second)))
    asyncio.run(provider.generate(ImageRequest(prompt="p", width=320, height=180, seed=99, output_path=third)))
    assert first.read_bytes() == second.read_bytes()      # same seed → identical art
    assert first.read_bytes() != third.read_bytes()       # different seed → different art


def test_demo_requires_output_path():
    with pytest.raises(ValueError):
        asyncio.run(DemoImageProvider().generate(ImageRequest(prompt="p", width=64, height=64)))


# --------------------------------------------------------------------- comfyui
def test_comfyui_full_queue_poll_download_flow(tmp_path):
    """Queue → poll history → download /view — with a real PNG payload at the end."""
    png = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(png, format="PNG")
    png_bytes = png.getvalue()
    state: dict = {"history_calls": 0, "prompt": None}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/prompt"):
            state["prompt"] = json.loads(request.content)
            return httpx.Response(200, json={"prompt_id": "job-1"})
        if "/history/" in url:
            state["history_calls"] += 1
            if state["history_calls"] < 2:            # first poll: still running
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"job-1": {"status": {"status_str": "success"},
                                                       "outputs": {"9": {"images": [
                                                           {"filename": "avf_00001_.png",
                                                            "subfolder": "", "type": "output"}]}}}})
        if "/view" in url:
            return httpx.Response(200, content=png_bytes)
        if url.endswith("/system_stats"):
            return httpx.Response(200, json={"system": {}})
        return httpx.Response(404)

    provider = ComfyUIImageProvider(endpoint="http://testserver",
                                    model="myCheckpoint.safetensors", http_client=_client(handler))
    out = tmp_path / "image.png"
    saved = asyncio.run(provider.generate(
        ImageRequest(prompt="a castle", negative_prompt="blurry", width=512, height=512,
                     seed=5, output_path=out, scene_ref="scene_001")))
    assert saved.read_bytes() == png_bytes

    workflow = state["prompt"]["prompt"]
    assert workflow["4"]["inputs"]["ckpt_name"] == "myCheckpoint.safetensors"
    assert workflow["6"]["inputs"]["text"] == "a castle"
    assert workflow["7"]["inputs"]["text"] == "blurry"
    assert workflow["3"]["inputs"]["seed"] == 5
    assert workflow["5"]["inputs"] == {"width": 512, "height": 512, "batch_size": 1}
    assert state["history_calls"] >= 2


def test_comfyui_workflow_error_surfaces(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/prompt"):
            return httpx.Response(200, json={"prompt_id": "job-2"})
        if "/history/" in url:
            return httpx.Response(200, json={"job-2": {
                "status": {"status_str": "error", "messages": ["killed"]}, "outputs": {"x": {}}}})
        return httpx.Response(404)

    provider = ComfyUIImageProvider(endpoint="http://testserver", http_client=_client(handler))
    with pytest.raises(ProviderResponseError, match="error"):
        asyncio.run(provider.generate(
            ImageRequest(prompt="p", width=64, height=64, output_path=tmp_path / "x.png")))


# -------------------------------------------------------------------- sd webui
def test_sd_webui_decodes_base64_png(tmp_path):
    png = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(png, format="PNG")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"images": [base64.b64encode(png.getvalue()).decode()]})

    provider = SDWebUIImageProvider(endpoint="http://testserver", http_client=_client(handler))
    out = tmp_path / "img.png"
    asyncio.run(provider.generate(ImageRequest(
        prompt="desert", negative_prompt="text", width=768, height=432, seed=11, output_path=out)))
    assert out.read_bytes() == png.getvalue()
    assert captured["payload"]["seed"] == 11
    assert captured["payload"]["width"] == 768 and captured["payload"]["height"] == 432


def test_sd_webui_empty_images_raises(tmp_path):
    provider = SDWebUIImageProvider(endpoint="http://testserver",
                                    http_client=_client(lambda r: httpx.Response(200, json={"images": []})))
    with pytest.raises(ProviderResponseError, match="no images"):
        asyncio.run(provider.generate(
            ImageRequest(prompt="p", width=64, height=64, output_path=tmp_path / "x.png")))


# ---------------------------------------------------------------------- clouds
def test_huggingface_posts_json_and_saves_bytes(tmp_path):
    png = io.BytesIO()
    Image.new("RGB", (16, 16)).save(png, format="PNG")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=png.getvalue())

    provider = create_image_provider("huggingface", api_key="hf-test")
    provider.endpoint = "http://testserver"
    provider._http_client = _client(handler)
    out = tmp_path / "hf.png"
    asyncio.run(provider.generate(ImageRequest(
        prompt="market at night", negative_prompt="blur", width=512, height=512, seed=3, output_path=out)))
    assert out.read_bytes() == png.getvalue()
    assert captured["url"].endswith(f"/models/{provider.model}")
    assert captured["auth"] == "Bearer hf-test"
    assert captured["payload"]["parameters"]["seed"] == 3


def test_stability_sends_form_and_saves_bytes(tmp_path):
    png = io.BytesIO()
    Image.new("RGB", (16, 16)).save(png, format="PNG")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, content=png.getvalue())

    provider = create_image_provider("stability", api_key="sk-stab")
    provider.endpoint = "http://testserver"
    provider._http_client = _client(handler)
    out = tmp_path / "st.png"
    asyncio.run(provider.generate(ImageRequest(
        prompt="storm", negative_prompt="", width=1024, height=1024, seed=8, output_path=out)))
    assert out.read_bytes() == png.getvalue()
    assert "/v2beta/stable-image/generate/core" in captured["url"]
    assert "seed=8" in captured["body"] and "output_format" in captured["body"]


def test_openai_image_size_mapping_and_b64(tmp_path):
    png = io.BytesIO()
    Image.new("RGB", (16, 16)).save(png, format="PNG")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png.getvalue()).decode()}]})

    provider = create_image_provider("openai", api_key="sk-o")
    provider.endpoint = "http://testserver"
    provider._http_client = _client(handler)
    out = tmp_path / "oa.png"

    asyncio.run(provider.generate(ImageRequest(prompt="p", width=1920, height=1080, output_path=out)))
    assert captured["payload"]["size"] == "1536x1024"      # landscape mapping
    asyncio.run(provider.generate(ImageRequest(prompt="p", width=1080, height=1920, output_path=out)))
    assert captured["payload"]["size"] == "1024x1536"      # portrait mapping
    assert out.read_bytes() == png.getvalue()


# ------------------------------------------------------------- factory & errors
def test_factory_image_provider_requires_key(monkeypatch):
    monkeypatch.delenv("STABILITY_API_KEY", raising=False)
    with pytest.raises(ProviderNotConfiguredError, match="STABILITY_API_KEY"):
        create_image_provider("stability")


def test_factory_builds_demo_image_provider():
    provider = create_image_provider("demo")
    assert isinstance(provider, DemoImageProvider)
    assert provider.model is None


def test_image_http_error_mapping(tmp_path):
    provider = SDWebUIImageProvider(endpoint="http://testserver",
                                    http_client=_client(lambda r: httpx.Response(500, text="boom")))
    with pytest.raises(ProviderResponseError, match="HTTP 500"):
        asyncio.run(provider.generate(
            ImageRequest(prompt="p", width=64, height=64, output_path=tmp_path / "x.png")))

    def refusing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    offline = SDWebUIImageProvider(endpoint="http://testserver", http_client=_client(refusing))
    with pytest.raises(ProviderConnectionError):
        asyncio.run(offline.generate(
            ImageRequest(prompt="p", width=64, height=64, output_path=tmp_path / "y.png")))
