"""Validated, deliberately small vocabulary for local photo edits."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PhotoStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    op: Literal["crop", "resize", "adjust", "twilight"]
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    strength: float | None = None
    fade_start: float | None = None
    fade_end: float | None = None

    @model_validator(mode="after")
    def check(self) -> PhotoStep:
        if self.op == "crop":
            if (self.x is None or self.y is None or self.x < 0 or self.y < 0
                    or self.width is None or self.height is None):
                raise ValueError("crop requires nonnegative x/y and positive width/height")
        elif self.op == "resize" and (self.width is None or self.height is None):
            raise ValueError("resize requires width and height")
        if self.op != "crop" and (self.x is not None or self.y is not None):
            raise ValueError("x/y are only valid for crop")
        if self.op in ("adjust", "twilight") and (self.width is not None or self.height is not None):
            raise ValueError(f"{self.op} does not take dimensions")
        if self.op != "adjust" and {"brightness", "contrast", "saturation"} & self.model_fields_set:
            raise ValueError("brightness/contrast/saturation are only valid for adjust")
        twilight_fields = {"strength", "fade_start", "fade_end"}
        if self.op == "twilight":
            if not twilight_fields <= self.model_fields_set:
                raise ValueError("twilight requires strength, fade_start and fade_end")
            if (self.strength is None or self.fade_start is None or self.fade_end is None
                    or not all(math.isfinite(v) for v in (self.strength, self.fade_start, self.fade_end))
                    or not 0 <= self.strength <= 1
                    or not 0 <= self.fade_start < self.fade_end <= 1):
                raise ValueError("twilight requires strength [0,1] and 0 <= fade_start < fade_end <= 1")
        elif twilight_fields & self.model_fields_set:
            raise ValueError("strength/fade_start/fade_end are only valid for twilight")
        for dimension in (self.width, self.height):
            if dimension is not None and not 1 <= dimension <= 8192:
                raise ValueError("width/height must be between 1 and 8192")
        for name, low, high in (("brightness", -1, 1), ("contrast", 0, 2), ("saturation", 0, 3)):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be finite and within [{low}, {high}]")
        return self


class PhotoSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,59}$")
    source: str = Field(min_length=1)
    steps: list[PhotoStep] = Field(min_length=1)
    output: str

    @model_validator(mode="after")
    def check(self) -> PhotoSpec:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.png", self.output):
            raise ValueError("output must be a single safe PNG filename")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        return self


def load_spec(path: Path) -> PhotoSpec:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("photo spec must be a YAML mapping")
    return PhotoSpec.model_validate(data)
