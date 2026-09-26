"""F0 spike: cua-driver round-trip — hidden launch, AX capture, background input, verify.

Flow (per-step timings measured):
  0. before: cursor position + active app
  1. launch_app Notepad (no focus steal — SW_SHOWNOACTIVATE)
  2. resolve pid / window_id
  3. get_window_state -> elements + screenshot (saved to spikes/out/)
  4. click the editor element (background) — addressed by element_token
     (bare element_index is refused: snapshot_id_required)
  5. type_text through the editor element (UIA SetValue path on Win11 Notepad)
  6. fresh get_window_state -> verify text landed (tree + status bar)
  7. after: cursor position + active app (focus check)
  8. kill_app (cleanup)

Prints a JSON report; also writes spikes/out/driver_report.json.

Usage:  uv run python spikes/spike_driver.py
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "spikes" / "out"
CUA = shutil.which("cua-driver") or "cua-driver"
MESSAGE = "hello from eeze " + datetime.now(UTC).strftime("%H:%M:%S")


def call(tool: str, payload: dict | None = None, timeout: int = 90) -> dict:
    """Invoke one cua-driver tool via the CLI; returns the parsed JSON + `_ms`."""
    cmd = [CUA, "call", tool] + ([json.dumps(payload)] if payload else [])
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", check=False,
        )
    except subprocess.TimeoutExpired:
        return {"_error": "timeout", "_ms": (time.perf_counter() - t0) * 1000}
    dt = (time.perf_counter() - t0) * 1000
    if proc.returncode != 0:
        return {"_error": (proc.stderr.strip() or proc.stdout.strip())[:400], "_ms": dt}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_error": f"non-JSON output: {proc.stdout[:200]!r}", "_ms": dt}
    if isinstance(data, dict):
        data["_ms"] = round(dt, 1)
        return data
    return {"_data": data, "_ms": dt}


def active_app(apps_resp: dict) -> str | None:
    return next(
        (a.get("name") for a in apps_resp.get("apps", []) if a.get("active")), None
    )


def notepad_window(launch_resp: dict) -> tuple[int | None, int | None]:
    pid = launch_resp.get("pid")
    wid = None
    for w in launch_resp.get("windows", []) or []:
        wid = w.get("window_id")
        break
    if pid and not wid:
        wins = call("list_windows")
        for w in wins.get("_legacy_windows", []) or wins.get("windows", []) or []:
            if w.get("pid") == pid:
                wid = w.get("window_id")
                break
    return pid, wid


def area(el: dict) -> int:
    f = el.get("frame") or {}
    return (f.get("w") or 0) * (f.get("h") or 0)


def slim(d: dict) -> dict:
    """Drop huge fields (screenshots) from a raw response for the report."""
    out = {}
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 300:
            out[k] = f"<str len={len(v)}>"
        else:
            out[k] = v
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"message": MESSAGE}

    report["cursor_before"] = call("get_cursor_position")
    report["active_before"] = active_app(call("list_apps"))

    launch = call("launch_app", {"name": "Notepad"})
    pid, wid = notepad_window(launch)
    if not pid:
        launch = call("launch_app", {"aumid": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"})
        pid, wid = notepad_window(launch)
    report["launch"] = slim({k: v for k, v in launch.items() if k != "windows"})
    if not pid:
        report["error"] = "could not launch Notepad"
        print(json.dumps(report, indent=2, default=str))
        raise SystemExit(1)
    report["pid"] = pid
    report["window_id"] = wid
    time.sleep(1.0)  # let the window materialize

    snap = call("get_window_state", {"pid": pid, "window_id": wid})
    report["capture_1"] = {
        k: snap.get(k)
        for k in (
            "_ms", "degraded", "degraded_reason", "total_element_count",
            "returned_element_count", "snapshot_id", "_error",
        )
    }
    if snap.get("screenshot_png_b64"):
        (OUT / "notepad_1.png").write_bytes(base64.b64decode(snap["screenshot_png_b64"]))

    elements = snap.get("elements", []) or []
    report["roles_seen"] = sorted({str(e.get("role", "")) for e in elements})[:25]

    editor = None
    for e in elements:
        if (
            str(e.get("role", "")).lower() in {"edit", "document", "richedit", "text"}
            and (editor is None or area(e) > area(editor))
        ):
            editor = e
    if editor is None:
        cands = [
            e for e in elements
            if any("value" in str(a).lower() for a in (e.get("actions") or []))
        ]
        editor = max(cands, key=area, default=None)
    report["editor_found"] = bool(editor)
    if editor:
        report["editor"] = {
            k: editor.get(k)
            for k in ("element_index", "element_token", "role", "label", "frame")
        }

    if editor:
        # NOTE: element actions must pass element_token (or snapshot_id+element_index);
        # a bare element_index is refused with code "snapshot_id_required".
        click = call("click", {
            "pid": pid, "window_id": wid, "element_token": editor["element_token"],
        })
        report["click"] = slim(click)
        typ = call("type_text", {
            "pid": pid, "window_id": wid,
            "element_token": editor["element_token"], "text": MESSAGE,
        })
        report["type"] = slim(typ)

    time.sleep(0.6)
    snap2 = call("get_window_state", {"pid": pid, "window_id": wid})
    report["capture_2_ms"] = snap2.get("_ms")
    if snap2.get("screenshot_png_b64"):
        (OUT / "notepad_2.png").write_bytes(base64.b64decode(snap2["screenshot_png_b64"]))
    haystack = json.dumps(snap2.get("elements", [])) + (snap2.get("tree_markdown") or "")
    report["verified_text_found"] = MESSAGE in haystack
    status = next(
        (
            e.get("label")
            for e in (snap2.get("elements") or [])
            if "characters" in str(e.get("label", ""))
        ),
        None,
    )
    report["status_bar_after"] = status

    report["cursor_after"] = call("get_cursor_position")
    report["active_after"] = active_app(call("list_apps"))

    kill = call("kill_app", {"pid": pid})
    report["kill"] = {k: kill.get(k) for k in ("_ms", "_error")}

    (OUT / "driver_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
