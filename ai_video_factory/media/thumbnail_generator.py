"""Smart thumbnail generator — 1280×720 with bold, editable text (spec §19).

Pure-Pillow rendering (no Qt): the bundled **Cairo** font (assets/fonts, SIL
OFL) carries Arabic + Latin, ``arabic_reshaper`` + ``python-bidi`` handle
right-to-left shaping, so thumbnails render identically on any machine — fully
offline and deterministic (same inputs → identical PNG bytes).

Layout: real background (a video frame / scene image, cover-cropped) or a
deterministic gradient fallback → dark bottom gradient for readability →
wrapped bold title with shadow + stroke → optional subtitle → optional badge
chip (e.g. the video duration).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from ai_video_factory.config.settings import project_root

THUMBNAIL_SIZE = (1280, 720)

#: accent palettes (bg gradient endpoints, chip colour) — chosen by title hash.
_PALETTES: tuple[tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((24, 30, 62), (72, 52, 130), (255, 179, 71)),
    ((14, 42, 58), (25, 121, 128), (244, 208, 63)),
    ((52, 18, 46), (128, 41, 88), (120, 220, 232)),
    ((30, 30, 34), (84, 84, 96), (255, 111, 97)),
    ((20, 50, 34), (46, 125, 70), (255, 219, 92)),
)

_ARABIC = re.compile(r"[\u0600-\u06FF]")


def _shape(text: str) -> str:
    """Reshape + bidi-reorder Arabic text for correct visual rendering."""
    text = (text or "").strip()
    if not _ARABIC.search(text):
        return text
    return get_display(arabic_reshaper.reshape(text))


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "Cairo-Bold.ttf" if bold else "Cairo-Regular.ttf"
    for path in font_candidates(name):       # packaged first, repo layout second
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()          # honest fallback (no Arabic then)


def font_candidates(name: str) -> list[Path]:
    """Font search paths: inside the installed package, then a repo checkout."""
    package_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    return [package_dir / name, project_root() / "assets" / "fonts" / name]


def _fit_font(text: str, *, bold: bool, max_size: int, min_size: int,
              max_width: int) -> ImageFont.FreeTypeFont:
    size = max_size
    while size > min_size and _font(bold, size).getlength(text) > max_width:
        size -= 4
    return _font(bold, size)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int,
          max_lines: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) > max_width and current:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        lines = [text]
    if len(lines) == max_lines:              # ellipsize the last line if cut
        joined = " ".join(words)
        if font.getlength(lines[-1]) >= max_width or joined != " ".join(
                lines[: max_lines - 1] + [lines[-1]]).strip():
            while font.getlength(lines[-1] + "…") > max_width and " " in lines[-1]:
                lines[-1] = lines[-1].rsplit(" ", 1)[0]
            lines[-1] += "…"
    return lines


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale + centre-crop to exactly *size* (like CSS object-fit: cover)."""
    target_w, target_h = size
    ratio = max(target_w / image.width, target_h / image.height)
    image = image.resize((max(1, round(image.width * ratio)),
                          max(1, round(image.height * ratio))), Image.LANCZOS)
    left = (image.width - target_w) // 2
    top = (image.height - target_h) // 2
    return image.crop((left, top, left + target_w, top + target_h))


def _gradient(size: tuple[int, int], top: tuple[int, int, int],
              bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    for y in range(height):
        t = y / max(height - 1, 1)
        colour = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        ImageDraw.Draw(image).line([(0, y), (width, y)], fill=colour)
    return image


def _bottom_shade(image: Image.Image, share: float = 0.62,
                  max_alpha: int = 200) -> None:
    """Darken the bottom part so white text always reads well."""
    width, height = image.size
    overlay = Image.new("L", (1, height), 0)
    start = int(height * (1.0 - share))
    for y in range(start, height):
        t = (y - start) / max(height - start, 1)
        overlay.putpixel((0, y), int(max_alpha * (t * t)))
    overlay = overlay.resize((width, height))
    black = Image.new("RGB", (width, height), (8, 8, 12))
    image.paste(black, (0, 0), overlay)


def format_duration(seconds: float) -> str:
    """``MM:SS`` (or ``H:MM:SS``) chip text from a duration."""
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def generate_thumbnail(
    output: Path | str,
    *,
    title: str,
    subtitle: str = "",
    badge: str = "",
    background: Path | str | None = None,
    size: tuple[int, int] = THUMBNAIL_SIZE,
) -> Path:
    """Render one smart thumbnail PNG (deterministic for identical inputs)."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    title = (title or "").strip() or "فيديو"
    digest = hashlib.sha256(title.encode()).digest()
    gradient_top, gradient_bottom, accent = _PALETTES[digest[0] % len(_PALETTES)]

    if background is not None and Path(background).exists():
        base = _cover(Image.open(Path(background)).convert("RGB"), size)
    else:
        base = _gradient(size, gradient_top, gradient_bottom)
    _bottom_shade(base)

    draw = ImageDraw.Draw(base)
    margin = 72
    max_text_width = width - margin * 2

    # ---------------------------------------------------------------- title
    font = _fit_font(_shape(title), bold=True, max_size=118, min_size=44,
                     max_width=max_text_width)
    lines = _wrap(_shape(title), font, max_text_width, max_lines=2)
    line_h = int(font.size * 1.22)
    block_h = line_h * len(lines)
    y = height - margin - block_h - (26 if subtitle else 0)
    for line in lines:
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text((margin + 6, y + 8), line, font=font,
                                    fill=(0, 0, 0, 190))
        base.paste(Image.alpha_composite(base.convert("RGBA"), shadow).convert("RGB"), (0, 0))
        draw = ImageDraw.Draw(base)
        draw.text((margin, y), line, font=font, fill=(255, 255, 255),
                  stroke_width=max(2, font.size // 26), stroke_fill=(10, 10, 14))
        y += line_h

    # ------------------------------------------------------------- subtitle
    if subtitle.strip():
        sub_font = _fit_font(_shape(subtitle), bold=False, max_size=52, min_size=26,
                             max_width=max_text_width)
        draw.text((margin, y - 4), _shape(subtitle), font=sub_font,
                  fill=(232, 232, 240),
                  stroke_width=2, stroke_fill=(10, 10, 14))

    # ---------------------------------------------------------------- badge
    if badge.strip():
        chip_font = _font(True, 40)
        text = _shape(badge)
        padding_x, padding_y = 26, 14
        chip_w = int(chip_font.getlength(text)) + padding_x * 2
        chip_h = 40 + padding_y * 2
        chip_x, chip_y = width - margin - chip_w, margin
        draw.rounded_rectangle(
            [chip_x, chip_y, chip_x + chip_w, chip_y + chip_h],
            radius=14, fill=accent)
        draw.text((chip_x + padding_x, chip_y + padding_y), text,
                  font=chip_font, fill=(18, 18, 24))

    base.save(output, format="PNG", optimize=True)
    return output
