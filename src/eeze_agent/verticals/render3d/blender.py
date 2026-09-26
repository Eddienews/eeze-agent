"""Blender discovery for the render3d vertical."""

from __future__ import annotations

import glob
import os
import re
import shutil
from pathlib import Path

GLOBS = (
    "C:/Program Files/Blender Foundation/Blender */blender.exe",
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/Applications/Blender.app/Contents/MacOS/Blender",
)


def _version_key(path: str) -> tuple[int, int]:
    match = re.search(r"Blender (\d+)(?:\.(\d+))?", path)
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2) or 0))


def find_blender(explicit: str | Path | None = None) -> Path:
    """Locate the Blender binary: explicit → ``EEZE_BLENDER`` → PATH → well-known installs.

    Multiple installs sort by VERSION (not lexicographically: "Blender 10.0" > "Blender 5.2")
    and the newest wins.
    """
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        raise FileNotFoundError(f"--blender path not found: {path}")
    env = os.environ.get("EEZE_BLENDER")
    if env and Path(env).is_file():
        return Path(env)
    which = shutil.which("blender")
    if which:
        return Path(which)
    found: list[str] = []
    for pattern in GLOBS:
        found += glob.glob(pattern)
    if found:
        found.sort(key=_version_key)
        return Path(found[-1])
    raise FileNotFoundError(
        "Blender not found — pass --blender PATH, set EEZE_BLENDER, or install Blender"
    )
