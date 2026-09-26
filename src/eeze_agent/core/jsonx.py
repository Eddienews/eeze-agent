"""Tolerant JSON extraction from chatty model replies (shared by planner/verticals)."""

from __future__ import annotations

import json


def first_json_object(text: str) -> str | None:
    """First balanced ``{...}`` block in ``text`` (string-aware), or None."""
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
                return text[start : index + 1]
    return None


def parse_json_object(text: str, *, what: str = "reply") -> dict:
    """Parse the first JSON object of a reply; raises ValueError with context."""
    raw = first_json_object(text or "")
    if raw is None:
        raise ValueError(f"no JSON object in {what}: {(text or '')[:200]}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {what}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TypeError(f"JSON in {what} is not an object")
    return parsed
