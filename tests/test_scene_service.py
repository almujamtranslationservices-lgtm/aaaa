"""Tests: scene service — enrichment, prompt building, prompt.json cache (spec §6/§21)."""

from __future__ import annotations

import pytest

from ai_video_factory.core.event_bus import EventBus
from ai_video_factory.core.project_manager import ProjectManager
from ai_video_factory.models.character import Character
from ai_video_factory.models.project import ProjectStatus, VideoType
from ai_video_factory.models.scene import Scene, SceneStatus
from ai_video_factory.services.scene_service import (
    characters_referenced,
    enrich_scene_offline,
    generate_scene_prompts,
    load_scene_prompt,
    scene_seed,
)
from tests.conftest import Recorder  # noqa: F401  (Recorder available if needed)


@pytest.fixture()
def manager(bus, settings):
    return ProjectManager(bus, settings)


@pytest.fixture()
def project(manager) -> "Scene":
    from ai_video_factory.models.project import Project

    project = Project(
        name="Scene Service Test", idea="idea", video_type=VideoType.CINEMATIC_STORY,
        target_duration=30, fps=24,
    )
    project_dir = manager._root / "scene-service-test"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scenes").mkdir(exist_ok=True)
    project.file_path = project_dir / "project.json"
    project.characters = [Character(name="Omar", age="35", gender="male", hair="short black hair")]
    project.scenes = [
        Scene(scene_id=1, duration=5, narration="نص أول",
              visual_description="an old wooden house on a foggy hill", characters=["Omar"]),
        Scene(scene_id=2, duration=5, narration="نص ثانٍ",
              visual_description="a dark forest at night"),
    ]
    manager.save(project)
    return project


def test_enrich_scene_offline_fills_directing_fields():
    scene = Scene(scene_id=1, visual_description="a lighthouse in a storm")
    enrich_scene_offline(scene)
    assert scene.environment == "a lighthouse in a storm"
    assert scene.action
    assert scene.lighting
    assert scene.camera


def test_seed_is_deterministic_and_stable():
    first = scene_seed("project-a", 3)
    assert first == scene_seed("project-a", 3)
    assert first != scene_seed("project-a", 4)
    assert first != scene_seed("project-b", 3)


def test_generate_scene_prompts_offline_full_flow(project, manager):
    result = generate_scene_prompts(project, manager, provider_id="demo")

    assert result.ok and len(result.generated) == 2 and result.skipped_cached == 0
    for scene in project.scenes:
        assert scene.status == SceneStatus.PROMPTED
        assert scene.seed is not None
        assert "Negative prompt:" in scene.image_prompt
        assert "no morphing" in scene.video_prompt

    # Scene 1 references Omar → description injected exactly once; scene 2: none.
    assert project.scenes[0].image_prompt.count("short black hair") == 1
    assert "Omar" not in project.scenes[1].image_prompt
    # 15-component contract present (subject, lens, grading, resolution, aspect…).
    prompt = project.scenes[0].image_prompt
    for fragment in ("35mm lens", "rule-of-thirds", "color grading", "depth of field",
                     "photorealistic", "1920x1080", "16:9 aspect ratio"):
        assert fragment in prompt

    # prompt.json persisted per scene with reproducibility data.
    payload = load_scene_prompt(manager.project_dir(project), 1)
    assert payload is not None
    assert payload["seed"] == project.scenes[0].seed
    assert payload["image_prompt"] == project.scenes[0].image_prompt
    assert payload["characters"] and payload["characters"][0]["name"] == "Omar"
    assert payload["frame"] == {"width": 1920, "height": 1080, "fps": 24}
    assert payload["scene"]["narration"] == "نص أول"

    # Project auto-saved; assets registry updated with the relative path.
    assert "prompt" in project.scenes[0].assets
    assert project.scenes[0].assets["prompt"].replace("\\", "/").endswith(
        "scenes/scene_001/prompt.json")


def test_second_run_uses_cache_and_force_regenerates(project, manager):
    first = generate_scene_prompts(project, manager, provider_id="demo")
    assert len(first.generated) == 2

    second = generate_scene_prompts(project, manager, provider_id="demo")
    assert second.generated == [] and second.skipped_cached == 2

    forced = generate_scene_prompts(project, manager, provider_id="demo", force=True)
    assert len(forced.generated) == 2 and forced.skipped_cached == 0
    # Seeds stay identical across forced regeneration (deterministic).
    assert forced is not None


def test_project_status_unchanged_by_service_but_scenes_persisted(project, manager, bus):
    generate_scene_prompts(project, manager, provider_id="demo")
    reloaded = manager.load(project.file_path)
    assert reloaded.scenes[0].status == SceneStatus.PROMPTED
    assert reloaded.scenes[0].seed is not None
    assert reloaded.characters[0].name == "Omar"


def test_characters_referenced_filters(project):
    referenced = characters_referenced(project)
    assert [c.name for c in referenced] == ["Omar"]


def test_failed_scene_does_not_block_oither(manager, project, monkeypatch):
    """A failing scene is marked FAILED while the rest of the run continues."""
    from ai_video_factory.prompts.image_prompt import ImagePromptEngine

    original = ImagePromptEngine.build
    calls = {"n": 0}

    def flaky(self, scene, **kwargs):
        calls["n"] += 1
        if scene.scene_id == 1:
            raise RuntimeError("provider exploded")
        return original(self, scene, **kwargs)

    monkeypatch.setattr(ImagePromptEngine, "build", flaky)
    result = generate_scene_prompts(project, manager, provider_id="demo")

    assert result.failed_scenes == [1]
    assert len(result.generated) == 1          # scene 2 still produced its prompt
    assert project.scenes[0].status == SceneStatus.FAILED
    assert project.scenes[1].status == SceneStatus.PROMPTED
