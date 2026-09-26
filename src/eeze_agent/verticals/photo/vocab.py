"""Photo writer vocabulary, kept in sync with PhotoStep by tests."""
from __future__ import annotations

from typing import Any

PHOTO_OPS: dict[str, dict[str, Any]] = {
    "crop": {
        "required": ["x", "y", "width", "height"],
        "optional": [],
        "what": "crop to a rectangle within the current image (x/y nonnegative; dimensions 1..8192)",
    },
    "resize": {
        "required": ["width", "height"],
        "optional": [],
        "what": "resize the current image to exact width and height (1..8192)",
    },
    "adjust": {
        "required": [],
        "optional": ["brightness", "contrast", "saturation"],
        "what": "adjust brightness [-1,1], contrast [0,2] and saturation [0,3]; "
                "omitted values mean 0, 1 and 1 respectively",
    },
    "twilight": {
        "required": ["strength", "fade_start", "fade_end"],
        "optional": [],
        "what": "blend a cool navy tint over the upper frame: strength [0,1], "
                "vertical fractions 0 <= fade_start < fade_end <= 1; fade to unchanged below "
                "fade_end. Positional gradient, NOT sky segmentation or scene relighting",
    },
}


def describe_photo_vocab() -> str:
    lines = [
        "PHOTO SPEC — one JSON object with fields:",
        "- name: lowercase slug (letters/digits/hyphens)",
        "- source: the EXACT absolute path of ONE provided PNG or JPEG, not its display name",
        ("- steps: ordered list; each step has unique id and one supported op; "
         "every step uses the previous image (first step uses source)"),
        "- output: a single safe .png filename, never a path",
        "OPS (required fields, optional fields):",
    ]
    for op, meta in PHOTO_OPS.items():
        lines.append(
            f"- {op}: required({', '.join(meta['required']) or '-'}) "
            f"optional({', '.join(meta['optional']) or '-'}) — {meta['what']}"
        )
    lines += [
        "CONSTRAINTS:",
        "- No invented source, no URLs, no commands or extra fields; the source is never modified.",
        "- Crop x+width/y+height must fit the source (or current resized image).",
        "- Only local image editing: no image generation and no external upload.",
    ]
    return "\n".join(lines)
