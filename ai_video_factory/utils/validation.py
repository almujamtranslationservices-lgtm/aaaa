"""LLM-output validation: JSON extraction, auto-repair and strict parsing.

LLMs frequently wrap JSON in markdown fences, use smart quotes or leave
trailing commas. :func:`parse_llm_json` applies a cascade of tolerant repairs
before giving up, satisfying the “validate JSON automatically and auto-repair
it” requirement (spec §7).
"""

from __future__ import annotations

import json
import re
from typing import Any

from ai_video_factory.core.exceptions import DataValidationError, JSONRepairError

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_PYTHON_LITERAL_RE = re.compile(r"\b(None|True|False|NaN|Infinity|-Infinity)\b")

_SMART_QUOTE_MAP = str.maketrans({
    "\u201c": '"', "\u201d": '"',   # “ ”
    "\u2018": "'", "\u2019": "'",   # ‘ ’
    "\u00a0": " ",                  # non-breaking space
})


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences, returning the first fenced block if any."""
    match = _FENCE_RE.search(text)
    return match.group(1).strip() if match else text.strip()


def extract_json_object(text: str) -> str | None:
    """Extract the first balanced ``{ … }`` block, string/escape aware."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def repair_json_text(text: str) -> str:
    """Best-effort repairs for the most common LLM JSON mistakes."""
    repaired = text.translate(_SMART_QUOTE_MAP).lstrip("\ufeff\u200b")
    repaired = _TRAILING_COMMA_RE.sub(r"\1", repaired)
    repaired = _PYTHON_LITERAL_RE.sub(
        lambda m: {"None": "null", "True": "true", "False": "false",
                   "NaN": "null", "Infinity": "null", "-Infinity": "null"}[m.group(1)],
        repaired,
    )
    # Single-quoted JSON (no double quotes anywhere) — convert quotes.
    if repaired and '"' not in repaired and "'" in repaired:
        repaired = repaired.replace("'", '"')
    return repaired


def parse_llm_json(text: str) -> dict[str, Any]:
    """Parse an LLM reply into a JSON object, applying auto-repair cascades.

    Raises:
        JSONRepairError: when every strategy fails.
    """
    if not text or not text.strip():
        raise JSONRepairError("Empty LLM response")

    fenced = strip_code_fences(text)
    extracted = extract_json_object(fenced) or extract_json_object(text)

    candidates: list[str] = []
    for fragment in (text.strip(), fenced, extracted or ""):
        if fragment:
            candidates.append(fragment)
            repaired = repair_json_text(fragment)
            candidates.append(repaired)
            # One more level: extract a balanced object from the repaired text.
            deeper = extract_json_object(repaired)
            if deeper:
                candidates.append(deeper)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return {"items": parsed}  # tolerate top-level arrays by wrapping

    preview = (text[:160] + "…") if len(text) > 160 else text
    raise JSONRepairError(f"Could not parse JSON from LLM output after auto-repair. Output was: {preview!r}")


def validate_project_name(name: str) -> str:
    """Validate and normalise a project name for creation."""
    name = (name or "").strip()
    if not name:
        raise DataValidationError("Project name must not be empty")
    if len(name) > 120:
        raise DataValidationError("Project name too long (max 120 characters)")
    return name


def validate_idea(idea: str, *, min_length: int = 10) -> str:
    """Validate the video idea text."""
    idea = (idea or "").strip()
    if len(idea) < min_length:
        raise DataValidationError(f"Video idea too short — describe it in at least {min_length} characters")
    return idea
