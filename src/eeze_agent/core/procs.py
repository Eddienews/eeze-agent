"""Small process helpers shared by the daemon and the routine reaper (stdlib only)."""

from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
from pathlib import Path


def _tasklist_row(pid: int) -> list[str] | None:
    """The ``tasklist`` CSV row for exactly ``pid`` (Windows), or ``None``."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for row in csv.reader(io.StringIO(out)):
        # "python.exe","1234","Console","1","10,000 K" — compare the PID column exactly,
        # a substring test would match 123 inside 1234.
        if len(row) >= 2 and row[1].strip() == str(int(pid)):
            return row
    return None


def pid_alive(pid: int | None) -> bool:
    if not pid or int(pid) <= 0:
        return False
    if sys.platform == "win32":
        return _tasklist_row(int(pid)) is not None
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False


def process_image(pid: int) -> str:
    """Lower-case executable name + command line (best effort; ``""`` when unknown)."""
    if sys.platform == "win32":
        row = _tasklist_row(pid)
        return row[0].strip().lower() if row else ""
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        return raw.replace(b"\0", b" ").decode("utf-8", "replace").strip().lower()
    except OSError:
        return ""


def looks_like_python(pid: int) -> bool:
    """True when ``pid`` is (still) a Python interpreter — guards against PID reuse.

    Unknown (no tasklist, no /proc) counts as True so behaviour on exotic systems is
    unchanged; a *known* non-Python image (a reused PID) returns False.
    """
    image = process_image(pid)
    return (not image) or ("python" in image) or ("eeze" in image)
