"""Subtitle system — cue extraction + SRT/ASS writers (spec §15).

Timing is derived from the REAL narration audio when it exists
(``scenes/scene_XXX/voice.wav``), otherwise from the speech-duration estimate
of the provider chain. Narration text is split on sentence punctuation, then
wrapped at a character budget without ever breaking a word; cue time is
distributed proportionally to cue length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ai_video_factory.media.audio_processor import wav_duration
from ai_video_factory.models.project import Project
from ai_video_factory.models.scene import Scene
from ai_video_factory.models.video import SubtitlePosition, SubtitleSettings

# ------------------------------------------------------------------- helpers
_SENTENCE_SPLIT = re.compile(r"[،؛.!?؟…\n]+")
_MAX_CUE_CHARS = 84            # ~ one comfortable reading line (Arabic or Latin)
_MAX_CUE_SECONDS = 5.0
_MIN_CUE_SECONDS = 0.8


@dataclass
class Cue:
    """One subtitle entry with absolute times (seconds)."""

    index: int
    start_s: float
    end_s: float
    text: str


def _format_srt_time(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_ass_time(seconds: float) -> str:
    centis = max(0, int(round(seconds * 100)))
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def ass_color(hex_color: str, *, alpha: int = 0) -> str:
    """``#RRGGBB`` → ASS ``&HAABBGGRR`` (with 0-255 alpha, 0 = opaque)."""
    match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", hex_color.strip())
    if not match:
        raise ValueError(f"invalid color: {hex_color!r}")
    r, g, b = (int(match.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


# --------------------------------------------------------------- cue builder
def split_narration(text: str, *, max_chars: int = _MAX_CUE_CHARS) -> list[str]:
    """Split narration into subtitle-sized chunks (words are never broken)."""
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue
        line, length = "", 0
        for word in sentence.split():
            candidate = f"{line} {word}".strip()
            if candidate and length + len(candidate) > max_chars and line:
                chunks.append(line)
                line, length = word, len(word)
            else:
                line, length = candidate, len(candidate)
        if line:
            chunks.append(line)
    return chunks


def build_scene_cues(
    scene: Scene,
    *,
    start_offset_s: float = 0.0,
    voice_path: Path | None = None,
) -> list[Cue]:
    """Cues for one scene, timed inside its real narration window.

    The window is the voice-over duration when a valid ``voice.wav`` exists,
    otherwise the provider-agnostic speech estimate clamped to the scene
    duration. Cue times are proportional to chunk length.
    """
    from ai_video_factory.ai.voice.demo import estimate_speech_duration

    chunks = split_narration(scene.narration)
    if not chunks:
        return []

    if voice_path is not None and voice_path.exists():
        try:
            window = wav_duration(voice_path)
        except Exception:  # noqa: BLE001 — corrupt WAV → estimate
            window = 0.0
    else:
        window = 0.0
    if window <= 0.0:
        window = estimate_speech_duration(scene.narration)
    window = min(window, max(scene.duration, window))          # never shorter than speech

    total_chars = sum(len(chunk) for chunk in chunks)
    cues: list[Cue] = []
    cursor = start_offset_s
    for index, chunk in enumerate(chunks, start=1):
        share = (len(chunk) / total_chars) * window if total_chars else window / len(chunks)
        duration = max(_MIN_CUE_SECONDS, min(_MAX_CUE_SECONDS, share))
        cues.append(Cue(index=index, start_s=cursor, end_s=cursor + duration, text=chunk))
        cursor += share                                          # no gaps between cues
    # Re-timestamp so cue list fits exactly inside [offset, offset + window].
    scale = window / max(cues[-1].end_s - cues[0].start_s, 1e-6)
    if abs(scale - 1.0) > 1e-6:
        base = cues[0].start_s
        for cue in cues:
            cue.start_s = base + (cue.start_s - base) * scale
            cue.end_s = base + (cue.end_s - base) * scale
    return cues


def build_project_cues(project: Project, scene_dir_of=None) -> list[Cue]:
    """All cues with absolute times across the assembled timeline."""
    cues: list[Cue] = []
    offset = 0.0
    for scene in project.scenes:
        voice_path = scene_dir_of(scene) / "voice.wav" if scene_dir_of else None
        scene_cues = build_scene_cues(scene, start_offset_s=offset, voice_path=voice_path)
        cues.extend(scene_cues)
        offset += max(scene.duration, 0.0)
    for index, cue in enumerate(cues, start=1):                 # global numbering
        cue.index = index
    return cues


# -------------------------------------------------------------------- writers
def cues_to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{cue.index}\n{_format_srt_time(cue.start_s)} --> {_format_srt_time(cue.end_s)}\n{cue.text}"
        for cue in cues
    ]
    return "\n\n".join(blocks) + "\n"


_ALIGNMENT = {
    SubtitlePosition.BOTTOM: 2,
    SubtitlePosition.CENTER: 5,
    SubtitlePosition.TOP: 8,
}
_ANIMATION_TAG = {
    "fade": r"{\fad(200,200)}",
    "pop": r"{\fscx80\fscy80\t(0,120,\fscx100\fscy100)}",
    "slide": r"{\move(60,0,0,0,0,150)}",
    "none": "",
}


def cues_to_ass(
    cues: list[Cue],
    settings: SubtitleSettings,
    *,
    width: int = 1280,
    height: int = 720,
) -> str:
    """Render cues as a complete ASS subtitle file honouring SubtitleSettings."""
    boxed = "box" in (settings.background or "").lower()
    primary = ass_color(settings.color)
    outline = ass_color(settings.stroke_color)
    back = ass_color("#000000", alpha=0x60) if boxed else ass_color("#000000", alpha=0xFF)
    margin_v = 40 if settings.position != SubtitlePosition.CENTER else 0

    header = (
        "[Script Info]\n"
        "; Generated by AI Video Factory\n"
        f"PlayResX: {width}\nPlayResY: {height}\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Narrator,{settings.font_family},{settings.font_size},"
        f"{primary},{primary},{outline},{back},0,0,0,0,100,100,0,0,"
        f"{3 if boxed else 1},{max(settings.stroke_width, 1)},"
        f"0,{_ALIGNMENT[settings.position]},40,40,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    tag = _ANIMATION_TAG.get(settings.animation, "")
    events = [
        f"Dialogue: 0,{_format_ass_time(cue.start_s)},{_format_ass_time(cue.end_s)},"
        f"Narrator,,0,0,0,,{tag}{cue.text}"
        for cue in cues
    ]
    return header + "\n".join(events) + "\n"
