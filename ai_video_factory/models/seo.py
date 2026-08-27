"""SEO / publication metadata models (spec §18).

A :class:`SEOPackage` is *editable by design*: the UI dialog mutates it, the
service persists it to ``seo.json`` next to the project, and every field has
platform-honest limits (YouTube: title ≤ 100, description ≤ 5000, tags ≤ 500
chars total, hashtags without spaces, chapters monotonic starting at 0).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class SEOChapter(BaseModel):
    """One ``MM:SS Title`` chapter marker."""

    start_s: float = Field(ge=0.0)
    title: str = Field(min_length=1, max_length=80)

    @property
    def timestamp(self) -> str:
        return _format_timestamp(self.start_s)

    def render(self) -> str:
        """The line YouTube expects inside the description."""
        return f"{self.timestamp} {self.title.strip()}"


class SEOPackage(BaseModel):
    """Publication metadata for one video."""

    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    hashtags: list[str] = Field(default_factory=list, max_length=15)
    chapters: list[SEOChapter] = Field(default_factory=list)
    language: str = "ar"

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in value:
            tag = tag.strip().strip("#")[:60]
            if tag and tag not in cleaned:
                cleaned.append(tag)
        if sum(len(tag) for tag in cleaned) > 500:
            keep, total = [], 0
            for tag in cleaned:                       # keep the head within budget
                if total + len(tag) + 1 > 500:
                    break
                keep.append(tag)
                total += len(tag) + 1
            return keep
        return cleaned

    @field_validator("hashtags")
    @classmethod
    def _clean_hashtags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in value:
            tag = "#" + "_".join(tag.strip().lstrip("#").split())[:30]
            if tag != "#" and tag not in cleaned:
                cleaned.append(tag)
        return cleaned

    @field_validator("chapters")
    @classmethod
    def _monotonic_chapters(cls, value: list[SEOChapter]) -> list[SEOChapter]:
        previous = -1.0
        for chapter in value:
            if chapter.start_s < previous:
                raise ValueError("SEO chapters must be sorted by start time")
            previous = chapter.start_s
        return value

    @property
    def chapters_block(self) -> str:
        """Ready-to-paste chapter lines for the description."""
        return "\n".join(chapter.render() for chapter in self.chapters)
