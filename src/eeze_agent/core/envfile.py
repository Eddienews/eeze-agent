"""Merge-updates for the local ``.env`` file (F5 wizard).

- ``read_env`` returns the parsed KEY=VALUE map (values as written, quotes stripped).
- ``update_env`` rewrites the file preserving comments, order, and unrelated keys;
  missing keys are appended. Values with spaces or ``#`` are quoted. Secret values are
  written through — callers must never echo or log them.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote, value = value[0], value[1:-1]
        if quote == '"':
            # Mirror python-dotenv (what the runtime actually loads): \" and \\ unescape.
            value = re.sub(r'\\([\\"])', r"\1", value)
    return (key, value) if key else None


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_line(line)
        if parsed:
            out[parsed[0]] = parsed[1]
    return out


def _format_value(value: str) -> str:
    if value == "" or any(ch in value for ch in " \t#'\""):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _check(key: str, value: str) -> None:
    """Refuse anything that could smuggle a second line into the file.

    A newline inside a value (say an IMAP user typed in the setup wizard) used to become a
    brand-new ``KEY=...`` line — e.g. ``EEZE_CODEX_BIN`` pointing at any program.
    """
    if not _KEY_RE.match(str(key)):
        raise ValueError(f"invalid env key: {key!r}")
    if any(ch in str(value) for ch in "\r\n\0"):
        raise ValueError(f"invalid value for {key}: line breaks are not allowed")


def update_env(path: Path, updates: dict[str, str]) -> None:
    """Merge ``updates`` into the env file, preserving everything else."""
    for key, value in updates.items():
        _check(key, value)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        parsed = _parse_line(line)
        if parsed and parsed[0] in remaining:
            key = parsed[0]
            out.append(f"{key}={_format_value(remaining.pop(key))}")
        else:
            out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.extend(f"{key}={_format_value(value)}" for key, value in remaining.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)  # holds passwords; Windows relies on the profile ACL
