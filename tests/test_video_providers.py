"""Tests: video providers — FFmpeg Ken Burns, ComfyUI template flow, Stability."""

from __future__ import annotations

import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from ai_video_factory.ai.factory import create_video_provider
from ai_video_factory.ai.video.base import VideoRequest
from ai_video_factory.ai.video.demo import DemoVideoProvider, pick_motion
from ai_video_factory.core.exceptions import ProviderResponseError
from ai_video_factory.models.video import MotionParams
from ai_video_factory.utils.ffmpeg_utils import FFmpegEngine


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")


def _make_image(path, width=320, height=180) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (40, 90, 140)).save(path, format="PNG")


def _engine() -> FFmpegEngine:
    engine = FFmpegEngine()
    if not engine.available:
        pytest.skip("ffmpeg not available")
    return engine


# ---------------------------------------------------------------- Ken Burns
@pytest.mark.parametrize("motion,expect", [
    ("zoom_in", "zoom_in"), ("zoom-out camera", "zoom_out"), ("slow pan left", "pan_left"),
    ("pan right movement", "pan_right"), ("static locked shot", "static"),
    ("anything else", "zoom_in"),
])
def test_pick_motion_hints_and_rotation(motion, expect):
    assert pick_motion(0, motion) == expect
    # No hint → rotates by scene index for variety.
    assert pick_motion(1, "") == "pan_right"


def test_ffmpeg_image_to_video_produces_valid_mp4(tmp_path):
    engine = _engine()
    image = tmp_path / "still.png"
    _make_image(image, 320, 180)
    out = tmp_path / "clip.mp4"
    engine.image_to_video(image, out, duration=1.0, fps=12, width=320, height=180,
                          motion="zoom_in")
    assert out.exists() and out.stat().st_size > 1000
    assert engine.validate_video(out) is True       # fully decodable


@pytest.mark.parametrize("motion", ["zoom_in", "zoom_out", "pan_left", "pan_right", "static"])
def test_ffmpeg_all_motions_encode(tmp_path, motion):
    engine = _engine()
    image = tmp_path / "still.png"
    _make_image(image, 160, 90)
    out = tmp_path / f"{motion}.mp4"
    engine.image_to_video(image, out, duration=0.5, fps=10, width=160, height=90, motion=motion)
    assert out.stat().st_size > 0


def test_ffmpeg_image_to_video_rejects_missing_image(tmp_path):
    engine = _engine()
    from ai_video_factory.core.exceptions import FFmpegError

    with pytest.raises(FFmpegError, match="not found"):
        engine.image_to_video(tmp_path / "nope.png", tmp_path / "x.mp4",
                              duration=1, fps=10, width=64, height=64)


def test_demo_video_provider_offline_chain(tmp_path):
    """Demo image → demo video: the full offline media chain works."""
    from ai_video_factory.ai.image.demo import DemoImageProvider

    image = tmp_path / "scene_001" / "image.png"
    asyncio.run(DemoImageProvider().generate(
        __import__("ai_video_factory.ai.image.base", fromlist=["ImageRequest"]).ImageRequest(
            prompt="p", width=320, height=180, seed=3, output_path=image, scene_ref="scene_001")))

    provider = DemoVideoProvider()
    if not provider._engine.available:
        pytest.skip("ffmpeg not available")
    out = tmp_path / "scene_001" / "video.mp4"
    saved = asyncio.run(provider.generate(VideoRequest(
        image_path=image, prompt="slow zoom", motion=MotionParams(
            duration_s=1.0, fps=12, seed=3, camera_motion="zoom_in"),
        width=320, height=180, output_path=out, scene_ref="scene_001")))
    assert saved.exists() and saved.stat().st_size > 1000
    assert provider._engine.validate_video(out)


def test_demo_video_provider_requires_image(tmp_path):
    provider = DemoVideoProvider()
    with pytest.raises(FileNotFoundError):
        asyncio.run(provider.generate(VideoRequest(
            image_path=tmp_path / "missing.png", output_path=tmp_path / "v.mp4")))


# ------------------------------------------------------------------- ComfyUI
def test_comfyui_video_template_flow(tmp_path):
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    state: dict = {"workflow": None, "upload_seen": False}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/upload/image"):
            state["upload_seen"] = True
            return httpx.Response(200, json={"name": "avf_scene_001.png", "subfolder": "", "type": "input"})
        if url.endswith("/prompt") and request.method == "POST":
            state["workflow"] = json.loads(request.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "i2v-1"})
        if "/history/" in url:
            return httpx.Response(200, json={"i2v-1": {
                "status": {"status_str": "success"},
                "outputs": {"20": {"gifs": [{"filename": "avf_i2v_00001.mp4",
                                             "subfolder": "", "type": "output"}]}}}})
        if "/view" in url:
            return httpx.Response(200, content=mp4)
        if url.endswith("/system_stats"):
            return httpx.Response(200, json={"system": {}})
        return httpx.Response(404)

    provider = create_video_provider("comfyui")
    provider.endpoint = "http://testserver"
    provider._http_client = _client(handler)
    provider.POLL_INTERVAL_S = 0.0

    image = tmp_path / "img.png"
    _make_image(image)
    out = tmp_path / "clip.mp4"
    saved = asyncio.run(provider.generate(VideoRequest(
        image_path=image, prompt="fog drifting", motion=MotionParams(
            duration_s=2.0, fps=12, seed=77, camera_motion="zoom_in"),
        width=512, height=288, output_path=out, scene_ref="scene_001")))

    assert saved.read_bytes() == mp4
    assert state["upload_seen"]
    workflow = state["workflow"]
    assert "_readme" not in workflow                          # doc keys stripped
    assert workflow["10"]["inputs"]["image"] == "avf_scene_001.png"   # uploaded name injected
    assert workflow["6"]["inputs"]["text"] == "fog drifting"
    assert workflow["3"]["inputs"]["seed"] == 77                       # typed int
    assert workflow["13"]["inputs"]["batch_size"] == 24               # frames = 2s * 12fps
    assert workflow["20"]["inputs"]["frame_rate"] == 12


def test_comfyui_video_no_output_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/upload/image"):
            return httpx.Response(200, json={"name": "x.png", "subfolder": "", "type": "input"})
        if url.endswith("/prompt"):
            return httpx.Response(200, json={"prompt_id": "i2v-2"})
        if "/history/" in url:
            return httpx.Response(200, json={"i2v-2": {"status": {"status_str": "success"},
                                                       "outputs": {"9": {}}}})
        return httpx.Response(404)

    provider = create_video_provider("comfyui")
    provider.endpoint = "http://testserver"
    provider._http_client = _client(handler)
    provider.POLL_INTERVAL_S = 0.0
    image = tmp_path / "img.png"
    _make_image(image)
    with pytest.raises(ProviderResponseError, match="no video"):
        asyncio.run(provider.generate(VideoRequest(
            image_path=image, output_path=tmp_path / "v.mp4")))


# ------------------------------------------------------------------ Stability
def test_stability_video_submit_poll_download(tmp_path):
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
    state: dict = {"polls": 0, "submit_body": None, "submit_files": None}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/image-to-video") and request.method == "POST":
            body = request.content.decode(errors="ignore")
            state["submit_body"] = body
            state["submit_files"] = "filename=" in request.headers.get("content-type", "")
            return httpx.Response(200, json={"id": "job-9"})
        if "/image-to-video/result/" in url:
            state["polls"] += 1
            if state["polls"] == 1:
                return httpx.Response(202)            # still rendering
            return httpx.Response(200, content=mp4)   # done
        return httpx.Response(404)

    provider = create_video_provider("stability", api_key="sk-stab")
    provider.endpoint = "http://testserver"
    provider._http_client = _client(handler)

    import ai_video_factory.ai.video.api as api_module
    api_module._POLL_INTERVAL_S = 0.0

    image = tmp_path / "img.png"
    _make_image(image, 64, 64)
    out = tmp_path / "clip.mp4"
    saved = asyncio.run(provider.generate(VideoRequest(
        image_path=image, prompt="subtle motion",
        motion=MotionParams(duration_s=4, fps=24, seed=5, motion_strength=8.0),
        width=768, height=768, output_path=out, scene_ref="scene_002")))

    assert saved.read_bytes() == mp4
    assert state["polls"] == 2
    assert "motion_bucket_id" in state["submit_body"] and "200" in state["submit_body"]  # 8.0*25
    assert "seed" in state["submit_body"]


def test_stability_video_http_error(tmp_path):
    provider = create_video_provider("stability", api_key="sk-stab")
    provider.endpoint = "http://testserver"
    provider._http_client = _client(lambda r: httpx.Response(402, text="credits exhausted"))
    image = tmp_path / "img.png"
    _make_image(image, 32, 32)
    with pytest.raises(ProviderResponseError, match="402"):
        asyncio.run(provider.generate(VideoRequest(
            image_path=image, output_path=tmp_path / "v.mp4")))
