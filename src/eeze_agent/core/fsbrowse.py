"""Folder browser for the local dashboard (the "Browse…" button next to a folder field).

A web page cannot learn a folder's full path from the OS picker, so the dashboard asks the
local service instead. Read-only: names of sub-folders (and optionally media files) only —
no file contents, no hidden/system entries. Only the paired local operator can call it.
"""

from __future__ import annotations

import os
import stat
import string
from pathlib import Path

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp", ".tif", ".tiff",
              ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
MAX_ENTRIES = 500


def _hidden(path: Path) -> bool:
    if path.name.startswith((".", "$", "~$")) or path.name.lower() in {"desktop.ini", "thumbs.db"}:
        return True
    try:
        attrs = getattr(path.stat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attrs & (getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2)
                         | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 4)))


def quick_places(home: Path | None = None) -> list[dict]:
    home = home or Path.home()
    places = [("Home", home)]
    for name in ("Desktop", "Pictures", "Videos", "Documents", "Downloads"):
        places.append((name, home / name))
    for base in sorted(home.glob("OneDrive*")):
        for name in ("Pictures", "Imagens", "Desktop", "Documents", "Documentos"):
            places.append((f"{base.name} · {name}", base / name))
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                places.append((f"{letter}:", drive))
    else:
        places.append(("/", Path("/")))
    seen, out = set(), []
    for label, path in places:
        if path.is_dir() and str(path) not in seen:
            seen.add(str(path))
            out.append({"label": label, "path": str(path)})
    return out


def list_dir(path: str | None, *, include_files: bool = False, home: Path | None = None) -> dict:
    """Sub-folders (and media files when asked) of ``path`` — default: the home folder."""
    raw = str(path or "").strip().strip('"').strip("'")
    folder = Path(raw) if raw else (home or Path.home())
    try:
        folder = folder.resolve()
    except OSError:
        pass
    if not folder.is_dir():
        raise FileNotFoundError(f"not a folder: {folder}")
    dirs: list[str] = []
    files: list[dict] = []
    media = 0
    truncated = False
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except PermissionError as exc:
        raise PermissionError(f"no permission to open {folder}") from exc
    for entry in entries:
        if _hidden(entry):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir:
            if len(dirs) < MAX_ENTRIES:
                dirs.append(entry.name)
            else:
                truncated = True
        elif entry.suffix.lower() in MEDIA_EXTS:
            media += 1
            if include_files and len(files) < MAX_ENTRIES:
                files.append({"name": entry.name, "path": str(entry)})
    parent = folder.parent if folder.parent != folder else None
    return {
        "path": str(folder),
        "parent": str(parent) if parent else None,
        "dirs": dirs,
        "files": files,
        "media_count": media,
        "truncated": truncated,
        "places": quick_places(home),
    }
