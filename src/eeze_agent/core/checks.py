"""Deterministic code checks for step verification.

Expression syntax (rendered with run vars before evaluation)::

    kind|arg1[|arg2]           one check
    kind|arg1; kind|arg2       several checks (AND)

Kinds:
    doc_equals|VALUE           the Document element's value equals VALUE
    field_equals|NEEDLE|VALUE  an Edit/ComboBox whose label contains NEEDLE has value VALUE
    file_exists|PATH           PATH exists on disk (polled up to ``timeout_s``)
    window_present|NEEDLE      a window title contains NEEDLE (polled)
    window_absent|NEEDLE       no window title contains NEEDLE (polled)
"""

from __future__ import annotations

import time
from pathlib import Path

from eeze_agent.core.models import Observation

POLL_S = 6.0
POLL_STEP_S = 0.4


def _poll(fn, timeout_s: float) -> tuple[bool, str]:
    deadline = time.time() + timeout_s
    last = ""
    while True:
        ok, last = fn()
        if ok or time.time() >= deadline:
            return ok, last
        time.sleep(POLL_STEP_S)


def _doc_value(obs: Observation | None) -> str | None:
    for e in (obs.elements if obs else []) or []:
        if str(e.get("role", "")).lower() == "document":
            return e.get("value")
    return None


def _field_value(obs: Observation | None, needle: str) -> tuple[bool, str]:
    for e in (obs.elements if obs else []) or []:
        role = str(e.get("role", "")).lower()
        label = str(e.get("label") or "").lower()
        if role in {"edit", "combobox"} and needle.lower() in label:
            return True, str(e.get("value"))
    return False, "field not found"


def run_check(
    expr: str,
    *,
    obs: Observation | None = None,
    driver=None,
    ctx=None,
    timeout_s: float = POLL_S,
) -> tuple[bool, str]:
    parts = [p.strip() for p in expr.split("|")]
    kind = parts[0]
    if kind == "doc_equals":
        want = parts[1]
        got = _doc_value(obs)
        return got == want, f"doc={got!r} want={want!r}"
    if kind == "field_equals":
        needle, want = parts[1], parts[2]
        found, got = _field_value(obs, needle)
        if not found:
            return False, got
        return got == want, f"field={got!r} want={want!r}"
    if kind == "file_exists":
        path = Path(parts[1])
        return _poll(lambda: (path.exists(), f"exists={path.exists()}"), timeout_s)
    if kind == "file_size_gt":
        path = Path(parts[1])
        want = int(parts[2])

        def _big() -> tuple[bool, str]:
            try:
                size = path.stat().st_size
            except OSError:
                size = -1
            return (size > want, f"size={size} want>{want}")

        return _poll(_big, timeout_s)
    if kind == "window_present":
        needle = parts[1]

        def _present() -> tuple[bool, str]:
            w = driver.find_window(ctx, needle)
            return (w is not None, f"window={w.get('title')!r}" if w else "absent")

        return _poll(_present, timeout_s)
    if kind == "window_absent":
        needle = parts[1]

        def _absent() -> tuple[bool, str]:
            w = driver.find_window(ctx, needle)
            return (w is None, f"present={w.get('title')!r}" if w else "absent")

        return _poll(_absent, timeout_s)
    return False, f"unknown check {kind!r}"
