"""The standard generation pipeline — every delivered stage wired for real.

``build_standard_pipeline`` assembles the concrete stages (script → scenes →
prompts → images → videos → voice → audio → subtitles → timeline → render →
export). SEO (PHASE 14) and the smart thumbnail (PHASE 15) slot in later with
their planned weights; every stage here maps to a name in ``PIPELINE_PLAN`` so
overall percentages match the documented UX contract.

All stages are idempotent and cache-aware: re-running a partially completed
project (resume after restart) skips finished work via the services' caches.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ai_video_factory.config.providers import ProviderKind, default_chain
from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.pipeline import (
    PIPELINE_PLAN, Pipeline, PipelineContext, PipelineStage, StageSkipRequested,
)
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.project import Project, ProjectStatus

logger = logging.getLogger(__name__)

#: Weights come from PIPELINE_PLAN so percentages match the documented contract.
_PLAN_WEIGHTS = {name: weight for name, weight, _ in PIPELINE_PLAN}

DEFAULT_PROVIDER_IDS: dict[str, str] = {
    kind.value: default_chain(kind)[0]      # free-first head of each chain
    for kind in ProviderKind
}


def _weight(name: str) -> float:
    return _PLAN_WEIGHTS.get(name, 1.0)


class _ServiceStage(PipelineStage):
    """Base: carries the shared dependencies every stage needs."""

    def __init__(self, manager: ProjectManager, *, provider_ids: dict[str, str],
                 models: dict[str, str | None], asset_repo=None) -> None:
        self.manager = manager
        self.provider_ids = provider_ids
        self.models = models
        self.asset_repo = asset_repo

    def provider_id(self, kind: str) -> str:
        return self.provider_ids.get(kind) or DEFAULT_PROVIDER_IDS.get(kind, "demo")

    def model(self, kind: str) -> str | None:
        return self.models.get(kind)


class ScriptGenerateStage(_ServiceStage):
    name = "script.generate"
    on_error = "retry"
    max_retries = 1

    def should_skip(self, ctx: PipelineContext) -> bool:
        return bool(ctx.project.scenes) or bool(ctx.get("script"))

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.script_service import generate_script

        project = ctx.project
        if len((project.idea or "").strip()) < 10:
            raise ValueError("project idea is too short (<10 chars) to generate a script")
        script = generate_script(
            idea=project.idea,
            language=project.settings.language,
            target_duration=project.target_duration,
            characters=project.characters,
            provider_id=self.provider_id("llm"),
            model=self.model("llm"),
            scene_count_hint=max(2, min(6, int(project.target_duration // 15) or 2)),
        )
        ctx.set("script", script)
        ctx.artifacts["script"] = Path("script.json")   # logical, in-project
        ctx.report_progress(1.0, f"script: {script.title}")


class ScriptValidateStage(_ServiceStage):
    """Real sanity checks between the script and the project's target."""

    name = "script.validate"

    def should_skip(self, ctx: PipelineContext) -> bool:
        return not bool(ctx.project.scenes)

    def run(self, ctx: PipelineContext) -> None:
        project = ctx.project
        scenes = project.scenes
        if not scenes:
            raise ValueError("script produced no scenes")
        total = sum(scene.duration for scene in scenes)
        if total <= 0:
            raise ValueError("script scenes have no total duration")
        target = project.target_duration
        if target > 0 and not (0.25 * target <= total <= 3.0 * target):
            logger.warning("Scene total %.1fs deviates from target %.1fs", total, target)
        project.status = ProjectStatus.SCRIPT_READY
        ctx.report_progress(1.0, f"{len(scenes)} scenes, {total:.0f}s total")


class ScenesBuildStage(_ServiceStage):
    name = "scenes.build"

    def should_skip(self, ctx: PipelineContext) -> bool:
        return bool(ctx.project.scenes)

    def run(self, ctx: PipelineContext) -> None:
        script = ctx.get("script")
        if script is None:
            raise StageSkipRequested("no new script — scenes already built")
        ctx.project.scenes = script.to_rich_scenes()
        ctx.report_progress(1.0, f"{len(ctx.project.scenes)} scenes built")


class PromptsStage(_ServiceStage):
    name = "prompts.generate"
    on_error = "skip"          # offline enrichment keeps DEMO MODE alive

    def should_skip(self, ctx: PipelineContext) -> bool:
        return all(
            (self.manager.asset_path(ctx.project, scene.scene_id, "prompt")).exists()
            for scene in ctx.project.scenes
        ) if ctx.project.scenes else False

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.scene_service import generate_scene_prompts

        generate_scene_prompts(
            ctx.project, self.manager,
            provider_id=self.provider_id("llm"), model=self.model("llm"),
            on_progress=lambda done, total, *_: ctx.report_progress(done / max(total, 1)),
        )


class ImagesStage(_ServiceStage):
    name = "images.generate"

    def should_skip(self, ctx: PipelineContext) -> bool:
        return all(self.manager.has_asset(ctx.project, s.scene_id, "image")
                   for s in ctx.project.scenes) if ctx.project.scenes else False

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.image_service import generate_scene_images

        generate_scene_images(
            ctx.project, self.manager,
            provider_id=self.provider_id("image"), model=self.model("image"),
            asset_repo=self.asset_repo,
            on_progress=lambda done, total, *_: ctx.report_progress(done / max(total, 1)),
        )


class VideosStage(_ServiceStage):
    name = "videos.generate"

    def should_skip(self, ctx: PipelineContext) -> bool:
        return all(self.manager.has_asset(ctx.project, s.scene_id, "video")
                   for s in ctx.project.scenes) if ctx.project.scenes else False

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.video_service import generate_scene_videos

        generate_scene_videos(
            ctx.project, self.manager,
            provider_id=self.provider_id("video"), model=self.model("video"),
            asset_repo=self.asset_repo,
            on_progress=lambda done, total, *_: ctx.report_progress(done / max(total, 1)),
        )


class VoiceStage(_ServiceStage):
    name = "voice.generate"

    def should_skip(self, ctx: PipelineContext) -> bool:
        return all(self.manager.has_asset(ctx.project, s.scene_id, "voice")
                   for s in ctx.project.scenes) if ctx.project.scenes else False

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.voice_service import generate_scene_voices

        generate_scene_voices(
            ctx.project, self.manager,
            provider_id=self.provider_id("voice"), model=self.model("voice"),
            asset_repo=self.asset_repo,
            on_progress=lambda done, total, *_: ctx.report_progress(done / max(total, 1)),
        )


class AudioSfxStage(_ServiceStage):
    """SFX per scene (procedural/offline until real SFX libraries land)."""

    name = "audio.sfx"
    on_error = "skip"

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.audio_service import generate_scene_sfx

        generated = generate_scene_sfx(ctx.project, self.manager)
        ctx.set("sfx_generated", [str(path) for path in generated])
        ctx.report_progress(1.0, f"{len(generated)} sfx")


class AudioMixStage(_ServiceStage):
    """Music bed + ducked per-scene mixes (the §14 audio bus)."""

    name = "audio.mix"
    on_error = "skip"

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.audio_service import generate_scene_mixes

        result = generate_scene_mixes(
            ctx.project, self.manager, asset_repo=self.asset_repo,
            on_progress=lambda done, total, _sid: ctx.report_progress(done / max(total, 1)),
        )
        if result.failed_scenes:
            raise RuntimeError(f"audio mix failed for scenes {result.failed_scenes}")


class SubtitlesStage(_ServiceStage):
    name = "subtitles.generate"
    on_error = "skip"

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.subtitle_service import generate_subtitles

        result = generate_subtitles(ctx.project, self.manager)
        ctx.set("subtitle_cues", result.cue_count)
        ctx.report_progress(1.0, f"{result.cue_count} cues")


class TimelineAssembleStage(_ServiceStage):
    name = "timeline.assemble"

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.render_service import assemble_timeline

        items = assemble_timeline(ctx.project, self.manager)
        total = sum(item.duration_s for item in items)
        ctx.set("timeline", items)
        ctx.set("timeline_total_s", total)
        ctx.report_progress(1.0, f"timeline: {len(items)} scenes, {total:.1f}s")


class RenderStage(_ServiceStage):
    name = "video.render"
    on_error = "retry"
    max_retries = 1

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.render_service import render_final_video

        result = render_final_video(
            ctx.project, self.manager,
            on_progress=lambda fraction, message: ctx.report_progress(fraction, message),
            force=bool(ctx.get("force_render")),
        )
        if not result.ok:
            raise RuntimeError(f"final render failed: {result.error}")
        ctx.artifacts["final"] = result.final_path
        ctx.artifacts["thumbnail"] = result.thumbnail_path
        ctx.set("render_result", result)


class SeoStage(_ServiceStage):
    """Publication metadata (title/description/tags/chapters) — editable later."""

    name = "seo.generate"
    on_error = "skip"

    def run(self, ctx: PipelineContext) -> None:
        from ai_video_factory.services.seo_service import generate_seo

        result = generate_seo(ctx.project, self.manager,
                              provider_id=self.provider_id("llm"),
                              model=self.model("llm"))
        if not result.ok:
            raise RuntimeError(f"SEO generation failed: {result.error}")
        ctx.set("seo", result.package)
        ctx.report_progress(1.0, f"seo: {result.package.title[:40]}")


class ExportStage(_ServiceStage):
    """Verify the final video, persist metadata and announce completion."""

    name = "export.final"

    def __init__(self, *args, bus: EventBus | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bus = bus

    def run(self, ctx: PipelineContext) -> None:
        import json

        final = ctx.artifacts.get("final")
        if final is None or not Path(final).exists():
            raise RuntimeError("export: final video missing")
        render_result = ctx.get("render_result")
        payload = {
            "final": str(final),
            "duration_s": round(render_result.duration_s, 3) if render_result else None,
            "resolution": f"{ctx.project.width}x{ctx.project.height}",
            "fps": ctx.project.fps,
            "providers": self.provider_ids,
            "scenes": len(ctx.project.scenes),
            "stages": render_result.stages if render_result else [],
        }
        info_path = Path(final).parent / "render_info.json"
        info_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        if self.asset_repo is not None:
            from ai_video_factory.utils.file_utils import sha256_file

            try:
                self.asset_repo.register(
                    ctx.project.id, 0, "final", Path(final),
                    sha256=sha256_file(Path(final)),
                    size_bytes=Path(final).stat().st_size,
                )
            except Exception:  # noqa: BLE001
                logger.warning("Registering final asset in DB skipped")
        if self._bus is not None:
            self._bus.publish(
                "render.completed", project_id=ctx.project.id,
                final=str(final), duration_s=payload["duration_s"],
            )
        ctx.report_progress(1.0, "export complete")


def build_standard_pipeline(
    manager: ProjectManager,
    *,
    bus: EventBus,
    provider_ids: dict[str, str] | None = None,
    models: dict[str, str | None] | None = None,
    asset_repo=None,
) -> Pipeline:
    """Assemble the full generation pipeline (all stages real & cached)."""
    deps = dict(
        manager=manager,
        provider_ids={**DEFAULT_PROVIDER_IDS, **(provider_ids or {})},
        models=models or {},
        asset_repo=asset_repo,
    )
    stages: list[PipelineStage] = [
        ScriptGenerateStage(**deps),
        ScriptValidateStage(**deps),
        ScenesBuildStage(**deps),
        PromptsStage(**deps),
        ImagesStage(**deps),
        VideosStage(**deps),
        VoiceStage(**deps),
        AudioSfxStage(**deps),
        AudioMixStage(**deps),
        SubtitlesStage(**deps),
        TimelineAssembleStage(**deps),
        RenderStage(**deps),
        SeoStage(**deps),
        ExportStage(**deps, bus=bus),
    ]
    for stage in stages:                      # percentages match PIPELINE_PLAN
        stage.weight = _weight(stage.name)
    return Pipeline(stages, bus=bus)


def make_context(project: Project, manager: ProjectManager, **data) -> PipelineContext:
    """Build a pipeline context rooted at the project's directory."""
    return PipelineContext(project=project, workdir=manager.project_dir(project), data=data)
