"""Watched folders: a Files mission that keeps its folder the way it describes.

A mission with ``schedule: {type: watch}`` has no clock. The routine scheduler (in the API
daemon, every tick) looks at the mission's folder instead:

1. The folder's *fingerprint* (names, sizes and modification times of the files directly
   inside it) must change, and then stay the same for ``EEZE_WATCH_SETTLE_S`` seconds
   (default 30) — a copy or download in progress never triggers a half-finished batch.
   Partial downloads (``.crdownload``, ``.part``…) keep the folder "busy".
2. Only then the mission's plan is previewed (nothing is touched). If it would change
   nothing — e.g. the files were just renamed by this same mission — the new state is
   simply remembered. Otherwise a run starts and, like every Files run, stops in
   Approvals with the full old → new list.
3. One run at a time: while a run is executing or waiting for a decision, the folder is
   not evaluated again; the latest state is looked at once it is over. A denied batch is
   not proposed again until the folder changes.

State lives in ``~/.eeze/watch/<routine>.json``. Nothing here moves or deletes files.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

PARTIAL_SUFFIXES = (".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp")
COOLDOWN_S = 60.0


def settle_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("EEZE_WATCH_SETTLE_S", "30")))
    except ValueError:
        return 30.0


def _state_path(home: Path, routine_id: str) -> Path:
    from eeze_agent.core.routines import path_safe

    return home / "watch" / f"{path_safe(routine_id)}.json"


def load_state(home: Path, routine_id: str) -> dict:
    try:
        data = json.loads(_state_path(home, routine_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(home: Path, routine_id: str, state: dict) -> None:
    path = _state_path(home, routine_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, path)


def fingerprint(folder: Path) -> str | None:
    """Digest of the files directly inside ``folder``; None if missing or still busy."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return None
    rows = []
    for entry in entries:
        name = entry.name
        if name.startswith((".", "~$")):
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if name.lower().endswith(PARTIAL_SUFFIXES):
            return None  # a download is still arriving
        rows.append(f"{name}\0{info.st_size}\0{info.st_mtime_ns}")
    rows.sort()
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def mission_spec(home: Path, routine_id: str):
    """The Files spec behind a ``mission:<id>`` routine, or None if it is not a Files mission."""
    import yaml

    from eeze_agent.core.missions import MissionStore, effective_plan
    from eeze_agent.verticals.files.spec import FilesSpec

    if not routine_id.startswith("mission:"):
        return None
    mission = MissionStore(home).get(routine_id.split(":", 1)[1])
    if not mission or mission.get("kind") != "files" or not str(mission.get("plan") or "").strip():
        return None
    data = yaml.safe_load(effective_plan(mission))
    return FilesSpec.model_validate(data) if isinstance(data, dict) else None


def evaluate(home: Path, routine_id: str, *, busy: bool, now: float | None = None) -> dict:
    """One look at a watched folder. Returns {"action": "run" | "wait" | "idle", "detail": ...}.

    ``busy`` = the routine already has a run executing or waiting for approval.
    The caller starts the run on ``"run"`` and then calls :func:`mark_triggered`.
    """
    from eeze_agent.verticals.files.runner import FilesError, plan_changes

    now = time.time() if now is None else now
    try:
        spec = mission_spec(home, routine_id)
    except Exception as exc:  # noqa: BLE001 — a broken plan must not stop the scheduler
        return {"action": "idle", "detail": f"plan unreadable: {type(exc).__name__}"}
    if spec is None:
        return {"action": "idle", "detail": "not a Files mission with a plan"}
    state = load_state(home, routine_id)
    current = fingerprint(spec.folder_path())
    if current is None:
        return {"action": "wait", "detail": "folder missing or a file is still arriving"}
    if state.get("fp") != current:
        state.update(fp=current, since=now)
        save_state(home, routine_id, state)
        return {"action": "wait", "detail": "folder changed — waiting for it to settle"}
    if now - float(state.get("since") or now) < settle_seconds():
        return {"action": "wait", "detail": "settling"}
    if state.get("evaluated") == current:
        return {"action": "idle", "detail": "no change since the last look"}
    if busy:
        return {"action": "wait", "detail": "a run is still open"}
    if now - float(state.get("last_trigger") or 0) < COOLDOWN_S:
        return {"action": "wait", "detail": "cooling down"}
    try:
        plan = plan_changes(spec)
    except (FilesError, OSError) as exc:
        state["evaluated"] = current
        save_state(home, routine_id, state)
        return {"action": "idle", "detail": f"cannot plan: {exc}"}
    work = len(plan["changes"]) if spec.op != "duplicates" else len(plan["duplicates"])
    if plan["conflicts"] or not work:
        state["evaluated"] = current
        save_state(home, routine_id, state)
        reason = f"{len(plan['conflicts'])} conflict(s) — fix them or run it by hand" if plan["conflicts"] \
            else "nothing to do"
        return {"action": "idle", "detail": reason}
    return {"action": "run", "detail": f"{work} change(s) to propose", "changes": work}


def mark_triggered(home: Path, routine_id: str, *, now: float | None = None) -> None:
    state = load_state(home, routine_id)
    state["evaluated"] = state.get("fp")
    state["last_trigger"] = time.time() if now is None else now
    save_state(home, routine_id, state)


def forget(home: Path, routine_id: str) -> None:
    """A fresh start (schedule saved again): the current folder state is evaluated anew."""
    try:
        _state_path(home, routine_id).unlink()
    except OSError:
        pass
