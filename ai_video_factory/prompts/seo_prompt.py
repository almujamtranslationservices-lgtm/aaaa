"""SEO metadata prompt builders (spec §27) — strict JSON contract."""

from __future__ import annotations

from ai_video_factory.utils.time_utils import format_duration

_SEO_JSON_EXAMPLE = """\
{
  "youtube_title": "…max 100 chars, high CTR…",
  "description": "…engaging description with keywords…",
  "keywords": ["keyword one", "keyword two"],
  "tags": ["tag1", "tag2"],
  "hashtags": ["#shorts"],
  "thumbnail_text": "3-5 punchy words",
  "pinned_comment": "question that drives engagement",
  "chapters": [{"time": "0:00", "title": "Intro"}]
}"""


def build_seo_system_prompt(*, language: str = "ar", include_chapters: bool = True) -> str:
    """System prompt for SEO metadata generation."""
    chapters_rule = (
        'Include "chapters": [{"time": "0:00", "title": "…"}] covering the whole video.'
        if include_chapters
        else 'Omit "chapters" entirely (short-form video).'
    )
    return f"""You are a YouTube SEO specialist.
Return ONE valid JSON object (no markdown, no commentary) with keys:
"youtube_title" (max 100 characters, compelling, not clickbait),
"description" (2-4 paragraphs, includes keywords naturally, first 2 lines hook the viewer),
"keywords" (10-15), "tags" (15-20, each under 30 characters),
"hashtags" (5-10, starting with #), "thumbnail_text" (3-5 words max),
"pinned_comment" (drives engagement, in LANGUAGE={language}).
{chapters_rule}
"title" and "description" are written in LANGUAGE={language}. Strict JSON syntax.

Example shape:
{_SEO_JSON_EXAMPLE}"""


def build_seo_user_prompt(*, title: str, script_summary: str, duration_s: float,
                          language: str = "ar") -> str:
    """User prompt with the video facts SEO is generated from."""
    return f"""Generate SEO metadata for this video.

TITLE: {title}
LANGUAGE: {language}
DURATION: {format_duration(duration_s)}
SCRIPT / SCENES SUMMARY:
{script_summary.strip()[:4000]}

Return ONLY the JSON object."""
