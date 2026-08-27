"""Tests: JSON extraction, auto-repair and strict LLM-JSON parsing."""

from __future__ import annotations

import pytest

from ai_video_factory.core.exceptions import JSONRepairError
from ai_video_factory.utils.validation import (
    extract_json_object,
    parse_llm_json,
    repair_json_text,
    strip_code_fences,
    validate_idea,
    validate_project_name,
)


def test_strip_code_fences_extracts_block():
    fenced = 'Sure! Here is the JSON:\n```json\n{"title": "X"}\n```\nDone.'
    assert strip_code_fences(fenced) == '{"title": "X"}'


def test_extract_json_object_balanced_and_string_aware():
    text = 'noise before {"a": {"b": "}}"}, "c": 1} noise after'
    assert extract_json_object(text) == '{"a": {"b": "}}"}, "c": 1}'


def test_extract_json_object_missing_close_returns_none():
    assert extract_json_object('{"a": 1') is None


def test_repair_trailing_commas_and_python_literals():
    broken = '{"a": [1, 2, 3,], "b": None, "c": True, "d": NaN}'
    repaired = repair_json_text(broken)
    assert parse_llm_json(repaired) == {"a": [1, 2, 3], "b": None, "c": True, "d": None}


def test_repair_smart_quotes():
    broken = "{\u201ctitle\u201d: \u201cقصة\u201d,}"
    assert parse_llm_json(broken) == {"title": "قصة"}


def test_repair_single_quoted_json():
    assert parse_llm_json("{'title': 'hello'}") == {"title": "hello"}


def test_parse_llm_json_with_fence_and_prose():
    reply = "Explanation…\n```json\n{\"title\": \"T\", \"scenes\": []}\n```\nHope this helps!"
    assert parse_llm_json(reply)["title"] == "T"


def test_parse_llm_json_wraps_top_level_array():
    assert parse_llm_json('[{"a": 1}]') == {"items": [{"a": 1}]}


def test_parse_llm_json_garbage_raises():
    with pytest.raises(JSONRepairError):
        parse_llm_json("no json here at all, sorry!")


def test_parse_llm_json_empty_raises():
    with pytest.raises(JSONRepairError):
        parse_llm_json("   ")


def test_validate_project_name_and_idea():
    assert validate_project_name("  فيديو الأول  ") == "فيديو الأول"
    with pytest.raises(Exception):
        validate_project_name("   ")
    with pytest.raises(Exception):
        validate_idea("قصير")
