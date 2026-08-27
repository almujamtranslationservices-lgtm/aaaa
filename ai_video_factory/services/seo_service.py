"""SEO service — publication metadata generation (spec §18).

Strategy (free-first, like everything else):

* ``demo`` provider → deterministic offline template built from the project's
  REAL content (scene narrations, durations, video type). No network.
* real LLM providers → one structured JSON call (repaired + validated);
  on any failure the template result is returned with a warning, never a crash.

Results are cached as ``seo.json`` next to the project and attached to
``project.seo`` — fully editable afterwards (``save_seo`` persists edits).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.project import Project
from ai_video_factory.models.seo import SEOPackage, SEOChapter

logger = logging.getLogger(__name__)

_TYPE_HASHTAGS: dict[str, list[str]] = {
    "youtube_video": ["#فيديو", "#يوتيوب"],
    "youtube_short": ["#شورتس", "#Shorts"],
    "tiktok": ["#تيك_توك", "#TikTok"],
    "instagram_reel": ["#ريلز", "#Reels"],
    "cinematic_story": ["#قصص", "#سينمائي"],
}

_TYPE_TAGS: dict[str, list[str]] = {
    "youtube_video": ["فيديو", "وثائقي قصير"],
    "youtube_short": ["شورتس", "مقاطع قصيرة"],
    "tiktok": ["تيك توك", "ترند"],
    "instagram_reel": ["ريلز", "انستغرام"],
    "cinematic_story": ["قصة", "سينما"],
}

_STOPWORDS = {
    "في", "من", "على", "عن", "إلى", "التي", "الذي", "هذا", "هذه", "ثم", "و", "أو",
    "مع", "كان", "كانت", "عند", "بعد", "قبل", "كل", "بين", "حتى", "كما", "the",
    "a", "an", "of", "and", "to", "in", "is", "are", "with", "for", "on", "over",
}


@dataclass
class SEOGenResult:
    package: SEOPackage | None = None
    cached: bool = False
    provider_id: str = "demo"
    used_fallback: bool = False          # LLM failed → template answered
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.package is not None


# ------------------------------------------------------------- offline template
def _top_keywords(text: str, limit: int = 8) -> list[str]:
    words: list[str] = []
    for raw in text.replace("\n", " ").split():
        word = raw.strip("،.!:؛؟\"'()[]").strip()
        if len(word) >= 3 and word.lower() not in _STOPWORDS and word not in words:
            words.append(word)
    return words[:limit]


def build_template_seo(project: Project, script_title: str | None = None) -> SEOPackage:
    """Deterministic offline SEOPackage from the project's real content."""
    narrations = [scene.narration.strip() for scene in project.scenes if scene.narration]
    title_base = script_title or project.name or project.idea[:60]
    title = title_base.strip()[:97].rstrip() + "…" if len(title_base.strip()) > 100 else title_base.strip()

    first_words = " ".join(narrations[0].split()[:14]) if narrations else project.idea[:80]
    description_lines = [first_words, ""]
    if narrations:
        description_lines.append("في هذا الفيديو:")
        description_lines.extend(f"• {line.split('.')[0][:80]}" for line in narrations[:6])
        description_lines.append("")
    chapters = _chapters_from_scenes(project)
    if chapters:
        description_lines.append("الفصول:")
        description_lines.append(SEOPackage(
            title="x", chapters=chapters).chapters_block)
    description_lines += ["", "#AI #VideoFactory"]
    description = "\n".join(description_lines)[:4990]

    keywords = _top_keywords(" ".join(narrations) or project.idea)
    type_key = project.video_type.value if hasattr(project.video_type, "value") else str(project.video_type)
    tags = [t for t in ([project.name[:40]] + keywords + _TYPE_TAGS.get(type_key, [])) if t.strip()]
    hashtags = list(dict.fromkeys(
        ["#" + k.replace(" ", "_") for k in keywords[:4]] + _TYPE_HASHTAGS.get(type_key, [])))

    return SEOPackage(title=title or "فيديو جديد", description=description,
                      tags=tags, hashtags=hashtags, chapters=chapters,
                      language=project.settings.language)


def _chapters_from_scenes(project: Project) -> list[SEOChapter]:
    """Chapter markers from the REAL timeline (cumulative scene durations)."""
    chapters: list[SEOChapter] = []
    cursor = 0.0
    for index, scene in enumerate(project.scenes, start=1):
        label = (scene.narration or scene.visual or f"المشهد {index}").strip()
        first_sentence = label.split(".")[0].split("،")[0].strip()
        chapters.append(SEOChapter(
            start_s=round(cursor, 2),
            title=(first_sentence[:40] or f"مشهد {index}")[:80],
        ))
        cursor += max(scene.duration, 0.0)
    return chapters


# ------------------------------------------------------------------ LLM prompt
_SEO_SYSTEM = """أنت خبير تحسين محركات البحث للفيديو. أعد JSON فقط بالبنية:
{"title": str<=100, "description": str<=2000, "tags": [str..12],
 "hashtags": [str..8 بدون #], "chapters": [{"start_s": float, "title": str}]}
باللغة المطلوبة، جذاب وصادق — لا مخالفات، لا نقرصنة عناوين."""


def _build_user_prompt(project: Project) -> str:
    scenes = "\n".join(
        f"{i}. [{scene.duration:.0f}s] {(scene.narration or scene.visual)[:100]}"
        for i, scene in enumerate(project.scenes, start=1))
    return (
        f"الفكرة: {project.idea}\nالنوع: {project.video_type.value}\n"
        f"المدة المستهدفة: {project.target_duration:.0f}ث\n"
        f"اللغة: {project.settings.language}\nالمشاهد:\n{scenes or '(لا مشاهد بعد)'}"
    )


def _parse_llm_seo(data: dict, project: Project) -> SEOPackage:
    if not isinstance(data, dict) or "title" not in data:
        raise ValueError("LLM SEO response missing 'title'")
    chapters = [
        SEOChapter(start_s=float(item.get("start_s", 0)), title=str(item.get("title", ""))[:80])
        for item in data.get("chapters", []) if str(item.get("title", "")).strip()
    ]
    if not chapters:
        chapters = _chapters_from_scenes(project)
    return SEOPackage(
        title=str(data["title"])[:100],
        description=str(data.get("description", ""))[:4990],
        tags=list(data.get("tags", []))[:30],
        hashtags=list(data.get("hashtags", []))[:15],
        chapters=chapters,
        language=project.settings.language,
    )


async def _generate_with_llm(project: Project, provider_id: str, model: str | None) -> SEOPackage:
    from ai_video_factory.ai.llm.base import LLMRequest
    from ai_video_factory.services.script_service import build_chain

    chain = build_chain(provider_id, model=model, fallback=True)
    request = LLMRequest(system=_SEO_SYSTEM, user=_build_user_prompt(project),
                         max_tokens=1200, temperature=0.6)
    data = await chain.generate_json(request)
    return _parse_llm_seo(data, project)


# ---------------------------------------------------------------------- service
def generate_seo(
    project: Project,
    manager: ProjectManager,
    *,
    provider_id: str = "demo",
    model: str | None = None,
    force: bool = False,
) -> SEOGenResult:
    """Generate (or load cached) SEO metadata for *project*."""
    seo_path = manager.project_dir(project) / "seo.json"
    if seo_path.exists() and not force:
        try:
            package = SEOPackage.model_validate_json(seo_path.read_text(encoding="utf-8"))
            project.seo = package
            return SEOGenResult(package=package, cached=True, provider_id=provider_id)
        except Exception:  # noqa: BLE001 — corrupt cache → regenerate
            logger.warning("Corrupt seo.json — regenerating")

    script_title = None
    script_path = manager.project_dir(project) / "script.json"
    if script_path.exists():
        try:
            script_title = json.loads(script_path.read_text(encoding="utf-8")).get("title")
        except Exception:  # noqa: BLE001
            script_title = None

    result = SEOGenResult(provider_id=provider_id)
    if provider_id == "demo":
        result.package = build_template_seo(project, script_title)
    else:
        import asyncio

        try:
            result.package = asyncio.run(_generate_with_llm(project, provider_id, model))
        except Exception as exc:  # noqa: BLE001 — SEO must never break the pipeline
            logger.warning("LLM SEO failed (%s) — template fallback used", exc)
            result.package = build_template_seo(project, script_title)
            result.used_fallback = True
            result.error = f"{type(exc).__name__}: {exc}"

    project.seo = result.package
    seo_path.write_text(result.package.model_dump_json(indent=2), encoding="utf-8")
    try:
        manager.save(project, autosave=True)
    except Exception:  # noqa: BLE001
        logger.exception("Auto-saving project '%s' after SEO failed", project.name)
    return result


def save_seo(project: Project, manager: ProjectManager, package: SEOPackage) -> Path:
    """Persist user edits (dialog Save) — project.seo + seo.json."""
    seo_path = manager.project_dir(project) / "seo.json"
    seo_path.write_text(package.model_dump_json(indent=2), encoding="utf-8")
    project.seo = package
    manager.save(project, autosave=True)
    return seo_path


def load_seo(project: Project, manager: ProjectManager) -> SEOPackage | None:
    seo_path = manager.project_dir(project) / "seo.json"
    if not seo_path.exists():
        return project.seo
    try:
        project.seo = SEOPackage.model_validate_json(seo_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("Could not load seo.json — keeping in-memory value")
    return project.seo
