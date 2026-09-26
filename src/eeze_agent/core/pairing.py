"""One-time pairing codes: open the dashboard already paired, without showing the token.

``eeze open`` (the "Eeze Agent" desktop shortcut) mints a random code, keeps only its
SHA-256 with a short expiry in ``~/.eeze/pair-codes.json`` and opens
``http://127.0.0.1:8765/pair#code=<code>``. The page trades the code for the usual
HttpOnly pairing cookie. A code works once, for two minutes, from this machine only (the
API's loopback checks still apply). Anyone able to run ``eeze open`` could already read
``~/.eeze/api.token``, so this adds convenience without widening access.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

CODE_TTL_S = 120
_FILE = "pair-codes.json"


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _load(home: Path) -> dict[str, float]:
    try:
        data = json.loads((home / _FILE).read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(home: Path, codes: dict[str, float]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    path = home / _FILE
    tmp = path.with_name(_FILE + ".tmp")
    tmp.write_text(json.dumps(codes), encoding="utf-8")
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def create_code(home: Path, *, now: float | None = None) -> str:
    now = time.time() if now is None else now
    code = secrets.token_urlsafe(24)
    codes = {k: v for k, v in _load(home).items() if v > now}  # drop expired ones
    codes[_digest(code)] = now + CODE_TTL_S
    _save(home, codes)
    return code


def consume_code(home: Path, code: str, *, now: float | None = None) -> bool:
    """True once for a valid, unexpired code; the code is gone afterwards either way."""
    if not isinstance(code, str) or not (16 <= len(code) <= 128):
        return False
    now = time.time() if now is None else now
    codes = _load(home)
    key = _digest(code)
    expires = codes.pop(key, None)
    codes = {k: v for k, v in codes.items() if v > now}
    _save(home, codes)
    return expires is not None and expires > now
