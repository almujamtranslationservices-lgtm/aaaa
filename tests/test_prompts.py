"""Tests: prompt builders (script / scene / image / video / SEO)."""

from __future__ import annotations

from ai_video_factory.models.character import Character
from ai_video_factory.models.project import AspectRatio, ResolutionPreset
from ai_video_factory.models.scene import Scene
from ai_video_factory.models.video import MotionParams
from ai_video_factory.prompts.image_prompt import ImagePromptEngine
from ai_video_factory.prompts.script_prompt import (
    build_script_system_prompt,
    build_script_user_prompt,
    estimate_scene_count,
)
from ai_video_factory.prompts.seo_prompt import build_seo_system_prompt, build_seo_user_prompt
from ai_video_factory.prompts.video_prompt import build_video_prompt


def test_estimate_scene_count_bounds():
    assert estimate_scene_count(30) == 6
    assert estimate_scene_count(10) == 3
    assert estimate_scene_count(100000) == 40


def test_script_system_prompt_pins_json_contract():
    prompt = build_script_system_prompt(language="ar", target_duration=60)
    for fragment in ("valid JSON", '"title"', '"scenes"', "LANGUAGE=ar", "60"):
        assert fragment in prompt


def test_script_user_prompt_includes_markers_and_bible():
    hero = Character(name="Omar", age="35", gender="male", hair="short black hair")
    prompt = build_script_user_prompt(
        "قصة اختفاء غامض", characters=[hero], target_duration=45, language="ar",
    )
    assert "VIDEO IDEA:" in prompt and "قصة اختفاء غامض" in prompt
    assert "LANGUAGE: ar" in prompt
    assert "TARGET DURATION (seconds): 45" in prompt
    assert "Omar:" in prompt and "short black hair" in prompt


def test_image_prompt_engine_components_and_single_character_injection():
    engine = ImagePromptEngine()
    hero = Character(name="Omar", age="35", gender="male", hair="short black hair")
    scene = Scene(
        scene_id=1, visual_description="an old house on a foggy hill",
        environment="foggy hill at dusk", camera="wide shot", lighting="moonlight",
        characters=["Omar"], action="walking toward the door",
    )
    prompt, negative = engine.build(
        scene, characters=[hero, Character(name="Sara")],
        resolution=ResolutionPreset.P1080, aspect_ratio=AspectRatio.R_16_9,
    )
    # 15-part contract
    for fragment in ("an old house", "Omar:", "35-year-old male", "foggy hill at dusk",
                     "walking toward the door", "wide shot", "35mm lens", "rule-of-thirds",
                     "moonlight", "color grading", "depth of field", "atmosphere",
                     "photorealistic", "cinematic", "1920x1080", "16:9 aspect ratio",
                     "Negative prompt:"):
        assert fragment in prompt, f"missing component: {fragment}"
    # only referenced characters are injected; unreferenced 'Sara' must not appear
    assert "Sara" not in prompt

    # A scene listing NO characters features none — nothing is injected.
    orphan_scene = Scene(scene_id=2, visual_description="empty street at dawn")
    orphan_prompt, _ = engine.build(orphan_scene, characters=[hero])
    assert "Omar" not in orphan_prompt
    # negative prompt returned separately too
    assert negative and "watermark" in negative


def test_image_prompt_never_duplicates_character_description():
    engine = ImagePromptEngine()
    hero = Character(name="Omar", hair="short black hair")
    description = hero.to_prompt_description()
    scene = Scene(scene_id=1, image_prompt=f"cinematic portrait, {description}", characters=["Omar"])
    prompt, _ = engine.build(scene, characters=[hero])
    assert prompt.count("short black hair") == 1  # description injected once, not twice


def test_video_prompt_composition():
    scene = Scene(scene_id=1, video_prompt="fog drifting", camera="slow push-in")
    prompt = build_video_prompt(scene, motion=MotionParams(motion_strength=8, camera_motion="zoom_in", duration_s=5, fps=30))
    assert "fog drifting" in prompt
    assert "zoom-in" in prompt
    assert "dynamic movement" in prompt
    assert "no morphing" in prompt
    assert "5 seconds" in prompt


def test_seo_prompts():
    system = build_seo_system_prompt(language="ar", include_chapters=True)
    assert "youtube_title" in system and "chapters" in system
    user = build_seo_user_prompt(title="قصة", script_summary="scenes…", duration_s=125.0)
    assert "02:05" in user  # duration rendered
