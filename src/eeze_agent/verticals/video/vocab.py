"""Video spec vocabulary — what the brain may express, derived from the code.

The table below is TEST-LOCKED against the pydantic validators (`tests/test_specwriter.py`):
every listed required field must make construction fail when missing, and a minimal step
carrying exactly the listed fields must construct. If the model changes, the test breaks.
"""

from __future__ import annotations

from typing import Any

# op -> {required: [fields], optional: [fields], what: str}
VIDEO_OPS: dict[str, dict[str, Any]] = {
    "still_to_video": {
        "required": ["source", "duration", "size"],
        "optional": ["fit"],
        "what": "turn a still image (a source) into a silent video clip; fit as in scale",
    },
    "trim": {
        "required": ["start", "duration"],
        "optional": ["end", "input"],
        "what": "cut a segment; needs start>=0 and duration>0 (an `end` time may replace `duration`); input = previous step by default",
    },
    "scale": {
        "required": ["size"],
        "optional": ["fit", "input"],
        "what": "resize to [width, height] (even numbers, h264); fit='fill' covers the whole "
                "frame and crops the overflow (USE THIS for vertical Reels/Shorts/TikTok from "
                "horizontal clips, and whenever the goal says fill/full-screen/no black bars), "
                "'fit' shows the whole picture with black bars, 'stretch' distorts",
    },
    "fps": {
        "required": ["fps"],
        "optional": ["input"],
        "what": "change the frame rate",
    },
    "concat": {
        "required": ["inputs"],
        "optional": [],
        "what": "join 2+ earlier step ids (or source names) into one clip; inputs must differ",
    },
    "thumbnail": {
        "required": ["at"],
        "optional": ["input"],
        "what": "extract a PNG cover frame at `at` seconds (image output, not a video)",
    },
}

SPEC_FIELDS = {
    "name": "short spec name (string)",
    "description": "one line about what the edit does (string)",
    "sources": "map of source name -> file path (absolute or repo-relative)",
    "steps": "ordered list; each step needs a unique id and an op; a step may only reference SOURCES and EARLIER step ids",
    "output": "file name of the deliverable, or the id of the step whose output is the deliverable",
}

CONSTRAINTS = [
    "sizes are [width, height] integers, both EVEN (h264/yuv420p), positive",
    "duration/start/end/at/fps are numbers (seconds, except fps)",
    "a step without `input` uses the PREVIOUS step's output",
    "concat inputs must all be earlier steps or sources (2 or more)",
    "the deliverable of a normal edit is a VIDEO; `thumbnail` produces a still (use it as a cover, not as `output` unless the goal asks for an image)",
]


def describe_video_vocab() -> str:
    """Compact, prompt-ready description of what a video spec can express."""
    lines = ["VIDEO SPEC — YAML object with fields:"]
    lines += [f"- {k}: {v}" for k, v in SPEC_FIELDS.items()]
    lines.append("OPS (step.op — required: field list):")
    for op, meta in VIDEO_OPS.items():
        req = ", ".join(meta["required"])
        opt = ", ".join(meta["optional"]) or "-"
        lines.append(f"- {op}: required({req}) optional({opt}) — {meta['what']}")
    lines.append("CONSTRAINTS:")
    lines += [f"- {c}" for c in CONSTRAINTS]
    return "\n".join(lines)
