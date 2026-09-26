"""The files spec: which folder, which files, and ONE operation. Strict and small on purpose."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".bmp", ".tif", ".tiff"]
VIDEO_EXTS = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"]
_TOKEN = re.compile(r"\{(n(?::0?\d)?|date|time|name|ext)\}")


class FilesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,59}$")
    folder: str = Field(min_length=1)
    op: Literal["rename", "organize", "duplicates"]
    # Which files: "images", "videos", "all" or explicit extensions like [".jpg", ".png"].
    include: Literal["images", "videos", "all"] | list[str] = "images"
    # rename
    pattern: str | None = None  # e.g. "park{n:03}" -> park001.jpg ; tokens: {n} {n:03} {date} {time} {name} {ext}
    start: int = Field(default=1, ge=0, le=1_000_000)
    order: Literal["name", "taken", "modified"] = "name"
    # organize
    by: Literal["month", "day", "year", "type"] = "month"

    @model_validator(mode="after")
    def _check(self) -> FilesSpec:
        if self.op == "rename":
            if not self.pattern:
                raise ValueError("rename needs a pattern, e.g. 'park{n:03}'")
            if "{n" not in self.pattern and "{name}" not in self.pattern:
                raise ValueError("the pattern needs {n} (a counter) or {name} so names stay unique")
            leftover = _TOKEN.sub("", self.pattern)
            if re.search(r"[{}]", leftover):
                raise ValueError("unknown {token} in pattern — use {n}, {n:03}, {date}, {time}, {name}")
            if re.search(r'[\\/:*?"<>|]', leftover):
                raise ValueError('the pattern cannot contain \\ / : * ? " < > |')
            if "{ext}" in self.pattern:
                raise ValueError("leave {ext} out — the original extension is always kept")
        elif self.pattern is not None:
            raise ValueError("pattern is only for rename")
        if isinstance(self.include, list):
            bad = [e for e in self.include if not re.fullmatch(r"\.[A-Za-z0-9]{1,6}", e)]
            if bad or not self.include:
                raise ValueError(f"include must be images|videos|all or extensions like ['.jpg']: {bad}")
        return self

    def extensions(self) -> set[str] | None:
        if self.include == "images":
            return set(IMAGE_EXTS)
        if self.include == "videos":
            return set(VIDEO_EXTS)
        if self.include == "all":
            return None
        return {e.lower() for e in self.include}

    def folder_path(self) -> Path:
        return Path(str(self.folder).strip().strip('"').strip("'"))


def load_spec(path: str | Path) -> FilesSpec:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("files spec must be a YAML mapping")
    return FilesSpec.model_validate(data)
