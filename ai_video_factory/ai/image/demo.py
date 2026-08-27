"""Demo image provider — real Pillow-rendered placeholder art (DEMO MODE, §36).

Generates a deterministic, seed-driven cinematic gradient composition (sky
gradient, horizon glow, vignette, grain) with the scene reference printed on
it. No network, no keys — yet a genuine PNG file with exact project
dimensions, so the whole pipeline (image → video → render) runs offline.
"""

from __future__ import annotations

import colorsys
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ai_video_factory.ai.image.base import ImageProvider, ImageRequest


def _seed_colors(seed: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Two harmonious gradient endpoints derived deterministically from *seed*."""
    rng = random.Random(seed)
    base_hue = rng.random()
    top = colorsys.hls_to_rgb(base_hue, 0.22, 0.6)
    bottom = colorsys.hls_to_rgb((base_hue + 0.08 + rng.random() * 0.12) % 1.0, 0.55, 0.55)
    to_255 = lambda c: tuple(int(channel * 255) for channel in c)  # noqa: E731
    return to_255(top), to_255(bottom)


class DemoImageProvider(ImageProvider):
    """Offline placeholder art generator (deterministic per seed)."""

    id = "demo"

    async def generate(self, request: ImageRequest) -> Path:
        if request.output_path is None:
            raise ValueError("DemoImageProvider requires request.output_path")
        width, height = max(16, request.width), max(16, request.height)
        seed = request.seed if request.seed is not None else 0
        top_color, bottom_color = _seed_colors(seed)
        rng = random.Random(seed)

        image = Image.new("RGB", (width, height), top_color)
        draw = ImageDraw.Draw(image)

        # Vertical sky gradient.
        for y in range(height):
            blend = y / max(1, height - 1)
            color = tuple(
                int(top + (bottom - top) * blend) for top, bottom in zip(top_color, bottom_color)
            )
            draw.line([(0, y), (width, y)], fill=color)

        # Horizon glow + celestial body, offset by seed.
        glow_x = int(width * (0.2 + 0.6 * rng.random()))
        horizon_y = int(height * (0.62 + 0.12 * rng.random()))
        glow_radius = int(min(width, height) * (0.10 + 0.08 * rng.random()))
        for ring in range(glow_radius * 3, glow_radius, -6):
            alpha_color = tuple(
                min(255, int(channel + (255 - channel) * 0.18)) for channel in bottom_color
            )
            draw.ellipse(
                [glow_x - ring, horizon_y - ring // 2, glow_x + ring, horizon_y + ring // 2],
                fill=alpha_color,
            )
        draw.ellipse(
            [glow_x - glow_radius // 3, horizon_y - glow_radius // 3,
             glow_x + glow_radius // 3, horizon_y + glow_radius // 3],
            fill=(255, 246, 220),
        )

        # Dark ground silhouette with rolling hills.
        ground_top = horizon_y + glow_radius // 2
        draw.polygon(
            [(0, height), (0, ground_top + 40),
             (int(width * 0.25), ground_top - 30), (int(width * 0.5), ground_top + 25),
             (int(width * 0.75), ground_top - 20), (width, ground_top + 35), (width, height)],
            fill=tuple(max(0, channel - 150) for channel in bottom_color),
        )

        # A few stars, deterministic positions.
        for _ in range(60):
            x, y = rng.randrange(width), rng.randrange(ground_top)
            brightness = 120 + rng.randrange(135)
            draw.point((x, y), fill=(brightness, brightness, min(255, brightness + 20)))

        image = image.filter(ImageFilter.GaussianBlur(radius=0.6))

        # Vignette (cheap: four edge gradients).
        vignette = Image.new("L", (width, height), 0)
        vignette_draw = ImageDraw.Draw(vignette)
        vignette_draw.rectangle(
            [int(width * 0.12), int(height * 0.12), int(width * 0.88), int(height * 0.88)],
            fill=255,
        )
        vignette = vignette.filter(ImageFilter.GaussianBlur(radius=min(width, height) // 8))
        black = Image.new("RGB", (width, height), (0, 0, 0))
        image = Image.composite(image, black, vignette)

        # Scene label — always visible, monospaced-ish default font.
        label = f"DEMO · {request.scene_ref or 'image'} · seed {seed}"
        draw = ImageDraw.Draw(image)
        font = _load_font(size=max(14, min(width, height) // 22))
        padding = 10
        text_bbox = draw.textbbox((0, 0), label, font=font)
        text_w, text_h = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
        corner = (padding, height - text_h - padding * 2)
        draw.rectangle(
            [corner[0] - 6, corner[1] - 6, corner[0] + text_w + 12, corner[1] + text_h + 10],
            fill=(0, 0, 0),
        )
        draw.text((corner[0], corner[1]), label, fill=(235, 238, 245), font=font)

        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG")
        return output


def _load_font(size: int):  # pragma: no cover — font availability varies by OS
    try:
        from PIL import ImageFont

        for name in ("DejaVuSansMono.ttf", "DejaVuSans.ttf", "Arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()
    except Exception:
        return None
