"""Tests: domain models (script validation, scene, character, prompt, project)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError as PydanticValidationError

from ai_video_factory.core.exceptions import ScriptValidationError
from ai_video_factory.models.character import Character
from ai_video_factory.models.prompt import DEFAULT_NEGATIVE_PROMPT, PromptComponents
from ai_video_factory.models.project import (
    AspectRatio,
    Project,
    ResolutionPreset,
    VideoType,
    resolution_dims,
)
from ai_video_factory.models.scene import Scene, SceneStatus, Script


def _script_payload(**overrides) -> dict:
    payload = {
        "title": "الاختفاء الغامض",
        "hook": "قبل مئة عام…",
        "scenes": [
            {"scene_id": 1, "duration": 5, "narration": "نص أول", "visual_description": "old house"},
            {"scene_id": 2, "duration": 6, "narration": "نص ثانٍ", "visual_description": "forest"},
        ],
    }
    payload.update(overrides)
    return payload


class TestScript:
    def test_from_clean_json(self):
        script = Script.from_llm_text(json.dumps(_script_payload(), ensure_ascii=False))
        assert script.title == "الاختفاء الغامض"
        assert script.scene_count == 2
        assert script.total_duration == pytest.approx(11.0)

    def test_from_fenced_messy_json_autorepaired(self):
        # Valid JSON with a trailing comma at the top level, wrapped in a fence.
        messy = "```json\n" + json.dumps(_script_payload(), ensure_ascii=False)[:-1] + ",}\n```"
        script = Script.from_llm_text(messy)  # trailing comma tolerated via repair
        assert script.scene_count == 2

    def test_missing_title_raises(self):
        with pytest.raises(ScriptValidationError):
            Script.from_llm_text(json.dumps({"hook": "x", "scenes": _script_payload()["scenes"]}))

    def test_empty_scenes_raises(self):
        with pytest.raises(ScriptValidationError):
            Script.from_llm_text(json.dumps({"title": "t", "scenes": []}))

    def test_non_object_root_raises(self):
        with pytest.raises(Exception):
            Script.from_llm_text(json.dumps(["not", "an", "object"]))

    def test_scene_ids_renumbered_when_missing_or_bad(self):
        payload = _script_payload()
        payload["scenes"] = [
            {"duration": 4, "narration": "a"},
            {"scene_id": "junk", "duration": 5, "narration": "b"},
        ]
        script = Script.from_llm_text(json.dumps(payload, ensure_ascii=False))
        assert [scene.scene_id for scene in script.scenes] == [1, 2]

    def test_to_rich_scenes(self):
        script = Script.from_llm_text(json.dumps(_script_payload(), ensure_ascii=False))
        scenes = script.to_rich_scenes()
        assert all(isinstance(scene, Scene) for scene in scenes)
        assert scenes[0].status == SceneStatus.SCRIPTED
        assert scenes[1].narration == "نص ثانٍ"


class TestSceneModel:
    def test_defaults(self):
        scene = Scene(scene_id=3)
        assert scene.duration == 5.0
        assert scene.characters == []
        assert scene.transition.value == "cut"

    def test_duration_bounds(self):
        with pytest.raises(PydanticValidationError):
            Scene(scene_id=1, duration=0.1)

    def test_characters_deduplicated(self):
        scene = Scene(scene_id=1, characters=["Omar", " Omar ", "Sara", None])  # type: ignore[list-item]
        assert scene.characters == ["Omar", "Sara"]


class TestCharacter:
    def test_prompt_description_contains_all_physical_fields(self):
        hero = Character(
            name="Omar", age="35", gender="male", height="tall (190cm)", body="athletic",
            face="angular face", hair="short black hair", eyes="brown eyes", skin="olive skin",
            clothes="dark wool coat", personality="calm", voice="deep", visual_style="photorealistic",
        )
        description = hero.to_prompt_description()
        for fragment in ("Omar:", "35-year-old male", "tall (190cm)", "short black hair",
                         "dark wool coat", "personality: calm", "visual style: photorealistic"):
            assert fragment in description

    def test_prompt_description_empty_character(self):
        assert Character(name="Ghost").to_prompt_description() == "Ghost."


class TestPromptComponents:
    def test_render_order_and_negative_last(self):
        components = PromptComponents(
            subject="a lonely lighthouse",
            character_descriptions=["Omar: 35-year-old male, tall."],
            environment="stormy coast at night",
            camera="wide shot",
            resolution="full HD 1080p",
            aspect_ratio="16:9 aspect ratio",
            negative_prompt=DEFAULT_NEGATIVE_PROMPT,
        )
        prompt = components.render()
        assert prompt.index("a lonely lighthouse") < prompt.index("Omar:")
        assert prompt.index("Omar:") < prompt.index("stormy coast at night")
        assert prompt.index("16:9 aspect ratio") < prompt.index("Negative prompt:")
        assert prompt.endswith(DEFAULT_NEGATIVE_PROMPT)

    def test_render_skips_empty_slots(self):
        assert PromptComponents(subject="cat").render() == "cat"


class TestProjectModel:
    @pytest.mark.parametrize("resolution,aspect,expected", [
        (ResolutionPreset.P1080, AspectRatio.R_16_9, (1920, 1080)),
        (ResolutionPreset.P1080, AspectRatio.R_9_16, (1080, 1920)),
        (ResolutionPreset.P1080, AspectRatio.R_1_1, (1080, 1080)),
        (ResolutionPreset.P720, AspectRatio.R_16_9, (1280, 720)),
        (ResolutionPreset.P480, AspectRatio.R_9_16, (480, 852)),
        (ResolutionPreset.P4K, AspectRatio.R_16_9, (3840, 2160)),
    ])
    def test_resolution_dims(self, resolution, aspect, expected):
        assert resolution_dims(resolution, aspect) == expected

    def test_resolution_dims_always_even(self):
        for resolution in ResolutionPreset:
            for aspect in AspectRatio:
                width, height = resolution_dims(resolution, aspect)
                assert width % 2 == 0 and height % 2 == 0

    def test_project_roundtrip_and_helpers(self):
        project = Project(
            name="Test", idea="idea text", video_type=VideoType.TIKTOK,
            aspect_ratio=AspectRatio.R_9_16, resolution=ResolutionPreset.P1080, fps=30,
            target_duration=30, characters=[Character(name="Omar")],
            scenes=[Scene(scene_id=1, duration=5), Scene(scene_id=2, duration=7)],
        )
        assert (project.width, project.height) == (1080, 1920)
        assert project.total_duration == 12.0
        assert project.scene_by_id(2).duration == 7  # type: ignore[union-attr]
        assert project.character("Omar").name == "Omar"  # type: ignore[union-attr]

        restored = Project.model_validate(json.loads(project.model_dump_json()))
        assert restored.character("Omar").name == "Omar"
        assert restored.width == 1080
        assert restored.file_path is None  # excluded from serialisation

    def test_fps_bounds(self):
        with pytest.raises(PydanticValidationError):
            Project(name="x", fps=5)
