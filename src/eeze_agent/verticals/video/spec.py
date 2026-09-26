"""Edit-spec models for the video vertical + YAML loader.

The spec is the contract between a brain (which writes it — C2) and the tools (which
execute it deterministically). Validation is strict and early: unknown op parameters,
missing required fields, odd sizes (h264) and dangling input references are refused
before any ffmpeg process starts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

OpName = Literal["still_to_video", "trim", "scale", "fps", "concat", "thumbnail"]
VIDEO_EXTS = {".mp4"}


class VideoStep(BaseModel):
    id: str
    op: OpName
    input: str | None = None  # step id or source name; default = the previous step
    source: str | None = None  # still_to_video: source name (image)
    inputs: list[str] | None = None  # concat: 2+ step ids (or source names)
    duration: float | None = None
    start: float | None = None
    end: float | None = None
    size: tuple[int, int] | None = None
    fps: float | None = None
    at: float | None = None
    # fit = whole frame visible with bars; fill = cover the frame, crop the overflow
    # (vertical reels from horizontal clips); stretch = distort to the exact size.
    fit: Literal["fit", "fill", "stretch"] = "fit"

    @model_validator(mode="after")
    def _check(self) -> VideoStep:
        def need(cond: bool, msg: str) -> None:
            if not cond:
                raise ValueError(f"step {self.id!r}: {msg}")

        if self.op == "still_to_video":
            need(bool(self.source), "source is required")
            need(self.duration is not None and self.duration > 0, "duration > 0 is required")
            need(self.size is not None, "size [w, h] is required")
        elif self.op == "trim":
            need(self.start is not None and self.start >= 0, "start >= 0 is required")
            need(
                (self.duration is not None and self.duration > 0)
                or (self.end is not None and self.end > (self.start or 0)),
                "duration > 0 (or end > start) is required",
            )
        elif self.op == "scale":
            need(self.size is not None, "size [w, h] is required")
        elif self.op == "fps":
            need(self.fps is not None and self.fps > 0, "fps > 0 is required")
        elif self.op == "concat":
            need(self.inputs is not None and len(self.inputs) >= 2, "inputs (2+) is required")
        elif self.op == "thumbnail":
            need(self.at is not None and self.at >= 0, "at >= 0 is required")

        if self.size is not None:
            w, h = self.size
            need(w > 0 and h > 0, "size must be positive")
            need(w % 2 == 0 and h % 2 == 0, "size must be even (h264/yuv420p)")
        if self.fps is not None:
            need(self.fps > 0, "fps > 0 is required")
        return self


class VideoSpec(BaseModel):
    name: str
    description: str = ""
    sources: dict[str, str] = Field(default_factory=dict)
    steps: list[VideoStep]
    output: str | None = None  # final file name, or the id of the step whose output is it

    @model_validator(mode="after")
    def _check_steps(self) -> VideoSpec:
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique")
        # forward-only references: a step may use sources and EARLIER step ids
        known = set(self.sources)
        for step in self.steps:
            refs = ([step.input] if step.input else []) + list(step.inputs or [])
            for ref in refs:
                if ref not in known:
                    raise ValueError(
                        f"step {step.id!r}: unknown input {ref!r} (known: {sorted(known)})"
                    )
            known.add(step.id)
        return self


def load_spec(path: Path) -> VideoSpec:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path}: spec file must contain a YAML mapping")
    return VideoSpec(**data)
