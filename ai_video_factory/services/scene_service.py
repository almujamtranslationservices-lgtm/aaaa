"""Scene generation service — script scenes ➜ rich scenes ➜ per-scene prompts.

Responsibilities (spec §6, §9, §10, §21):

1. **Enrich** each scripted scene with the missing directing fields
   (environment / action / lighting). Two paths:
   * LLM path — uses the scene-refinement prompt through the provider chain
     (any implemented provider; falls back to the offline path on failure).
   * Offline path — deterministic heuristics from the visual description
     (always available; used as-is when the provider is ``demo``).
2. **Build prompts** — the full 15-component image prompt (with Character
   Bible injected exactly once) and the image-to-video motion prompt.
3. **Persist** ``scenes/scene_XXX/prompt.json`` containing the exact prompts,
   seeds and character descriptions used — reproducibility + cache identity.

Cache rule (spec §21): a scene whose ``prompt.json`` already exists and whose
status is already ``prompted`` is skipped unless ``force=True`` — a failure at
scene 6 never regenerates scenes 1-5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_video_factory.ai.llm.base import LLMProvider, LLMRequest
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.character import Character
from ai_video_factory.models.project import Project
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.models.video import MotionParams
from ai_video_factory.prompts.image_prompt import ImagePromptEngine
from ai_video_factory.prompts.scene_prompt import build_scene_system_prompt, build_scene_user_prompt
from ai_video_factory.prompts.video_prompt import build_video_prompt
from ai_video_factory.services.script_service import build_chain
from ai_video_factory.utils.file_utils import atomic_write_json, read_json

logger = logging.getLogger(__name__)

#: Fields the LLM scene pass may fill (narration is preserved as-authored).
_ENRICH_FIELDS: tuple[str, ...] = (
    "visual_description", "environment", "action", "camera", "lighting",
    "sfx", "music", "image_prompt", "video_prompt",
)

_LIGHTING_PRESETS: tuple[str, ...] = (
    "moody low-key lighting with strong rim light",
    "soft natural light, overcast diffusion",
    "warm golden-hour light, long shadows",
    "cold blue night lighting, practical sources",
    "dramatic chiaroscuro contrast",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def scene_seed(project_id: str, scene_id: int) -> int:
    """Deterministic per-scene seed (reproducibility across reruns)."""
    import hashlib

    digest = hashlib.sha256(f"{project_id}:{scene_id}".encode()).hexdigest()
    return int(digest[:8], 16) % (2**31 - 1)


def enrich_scene_offline(scene: Scene) -> None:
    """Fill missing directing fields with deterministic heuristics (no LLM)."""
    if not scene.environment:
        scene.environment = scene.visual_description.strip() or scene.title
    if not scene.action:
        scene.action = "subtle environmental motion"
    if not scene.lighting:
        scene.lighting = _LIGHTING_PRESETS[scene.scene_id % len(_LIGHTING_PRESETS)]
    if not scene.camera:
        scene.camera = "cinematic establishing shot"


async def _enrich_scene_via_llm(
    scene: Scene, chain_llm: LLMProvider, *, language: str,
) -> bool:
    """Try to enrich one scene through the LLM. Returns ``True`` on success."""
    from ai_video_factory.utils.validation import parse_llm_json

    system = build_scene_system_prompt(language=language)
    user = build_scene_user_prompt(scene)
    text = await chain_llm.generate(LLMRequest(system=system, user=user, temperature=0.7))
    try:
        data = parse_llm_json(text)
    except Exception as exc:  # noqa: BLE001 — malformed enrichment is not fatal
        logger.warning("Scene %d: LLM enrichment unparsable (%s) — using offline path",
                       scene.scene_id, exc)
        return False
    applied = 0
    for key in _ENRICH_FIELDS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            setattr(scene, key, value.strip())
            applied += 1
    duration = data.get("duration")
    if isinstance(duration, (int, float)) and 0.5 <= float(duration) <= 120.0:
        scene.duration = float(duration)
        applied += 1
    transition = data.get("transition")
    if isinstance(transition, str) and transition in {t.value for t in scene.transition.__class__}:
        from ai_video_factory.models.scene import Transition

        scene.transition = Transition(transition)
        applied += 1
    return applied > 0


@dataclass
class ScenePromptsResult:
    """Summary of one scene-prompt generation run."""

    generated: list[Path] = field(default_factory=list)
    skipped_cached: int = 0
    failed_scenes: list[int] = field(default_factory=list)
    provider_id: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed_scenes


def generate_scene_prompts(
    project: Project,
    manager: ProjectManager,
    *,
    provider_id: str = "demo",
    model: str | None = None,
    language: str | None = None,
    force: bool = False,
) -> ScenePromptsResult:
    """Enrich scenes, build prompts and persist ``prompt.json`` per scene.

    Args:
        project: the project (mutated in place; auto-saved at the end).
        manager: ProjectManager used for cache paths and saving.
        provider_id: LLM used for enrichment (``demo`` = offline heuristics).
        force: regenerate even when a cached prompt.json exists.
    """
    import asyncio

    result = ScenePromptsResult(provider_id=provider_id)
    if not project.scenes:
        return result

    language = language or project.settings.language
    engine = ImagePromptEngine()
    use_llm = provider_id != "demo"
    chain = build_chain(provider_id, model=model) if use_llm else None

    for scene in project.scenes:
        prompt_path = manager.asset_path(project, scene.scene_id, "prompt")
        if (
            not force
            and prompt_path.exists()
            and scene.status != SceneStatus.PENDING
            and scene.status != SceneStatus.SCRIPTED
        ):
            scene.assets.setdefault("prompt", _relative_prompt(project, prompt_path))
            result.skipped_cached += 1
            continue

        seed = scene.seed if scene.seed is not None else scene_seed(project.id, scene.scene_id)

        try:
            if scene.status == SceneStatus.SCRIPTED or force:
                if chain is not None:
                    enriched = asyncio.run(_enrich_scene_via_llm(scene, chain, language=language))
                    if not enriched:
                        enrich_scene_offline(scene)
                else:
                    enrich_scene_offline(scene)

            image_prompt, negative_prompt = engine.build(
                scene,
                characters=project.characters,
                resolution=project.resolution,
                aspect_ratio=project.aspect_ratio,
            )
            video_prompt = build_video_prompt(
                scene,
                motion=MotionParams(
                    duration_s=min(scene.duration, 12.0),
                    fps=project.fps,
                    seed=seed,
                ),
            )
            scene.image_prompt = image_prompt
            scene.video_prompt = video_prompt
            scene.seed = seed

            payload: dict[str, Any] = {
                "scene_id": scene.scene_id,
                "seed": seed,
                "provider": {"llm": provider_id},
                "image_prompt": image_prompt,
                "negative_prompt": negative_prompt,
                "video_prompt": video_prompt,
                "characters": [
                    {"name": c.name, "description": c.to_prompt_description()}
                    for c in project.characters
                    if not scene.characters or c.name in scene.characters
                ],
                "scene": {
                    "title": scene.title,
                    "duration": scene.duration,
                    "narration": scene.narration,
                    "visual_description": scene.visual_description,
                    "environment": scene.environment,
                    "action": scene.action,
                    "camera": scene.camera,
                    "lighting": scene.lighting,
                    "sfx": scene.sfx,
                    "music": scene.music,
                    "transition": scene.transition.value,
                },
                "frame": {"width": project.width, "height": project.height, "fps": project.fps},
                "generated_at": _now_iso(),
            }
            atomic_write_json(prompt_path, payload)
            scene.assets["prompt"] = _relative_prompt(project, prompt_path)
            scene.status = SceneStatus.PROMPTED
            result.generated.append(prompt_path)
            logger.info("Scene %03d prompts ready (seed=%d) → %s",
                        scene.scene_id, seed, prompt_path.name)
        except Exception as exc:  # noqa: BLE001 — one scene must not kill the run
            scene.status = SceneStatus.FAILED
            result.failed_scenes.append(scene.scene_id)
            logger.exception("Scene %d prompt generation failed: %s", scene.scene_id, exc)

    try:
        manager.save(project, autosave=True)
    except Exception:  # noqa: BLE001 — saving errors are logged by the manager
        logger.exception("Auto-saving project '%s' after scene prompts failed", project.name)
    return result


def load_scene_prompt(project_dir: Path, scene_number: int) -> dict[str, Any] | None:
    """Read ``scenes/scene_XXX/prompt.json`` (cache introspection)."""
    path = project_dir / "scenes" / f"scene_{scene_number:03d}" / "prompt.json"
    if not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def _relative_prompt(project: Project, prompt_path: Path) -> str:
    """Path of the prompt file relative to the project directory."""
    try:
        return str(prompt_path.relative_to(manager_dir(project)))
    except ValueError:
        return str(prompt_path)


def manager_dir(project: Project) -> Path:
    """Directory of ``project.json`` for *project*."""
    if project.file_path is None:
        raise ValueError("Project has no file path — save it first")
    return project.file_path.parent


def characters_referenced(project: Project) -> list[Character]:
    """Characters actually referenced by at least one scene."""
    referenced = {name for scene in project.scenes for name in scene.characters}
    return [c for c in project.characters if c.name in referenced]
