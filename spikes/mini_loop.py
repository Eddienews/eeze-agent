"""F0 spike: the smallest real observe → decide → act → verify loop.

One Notepad window, N iterations. Each iteration writes a unique token into the
document and verifies it — but every decision goes through Jev:

  observe : get_window_state (fresh snapshot) -> compact element state
  decide  : Jev Choice — which candidate element receives the input?
  act     : set_value (replace) or type_text (insert) on the chosen element_token
  verify  : fresh snapshot + Jev Noul — does the document content equal the token?

Records per-iteration timings, Jev latencies and token usage, Python-side
cross-check, and a summary (cycle p50/p95, cost/cycle, success rate).
Writes spikes/out/mini_loop_report.json and notepad_loop.png.

Usage:  uv run python spikes/mini_loop.py [N] [set_value|type_text]
"""

from __future__ import annotations

import base64
import json
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from typesafe_sdk import Choice, Noul, TypeSafeClient

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "spikes" / "out"
CUA = shutil.which("cua-driver") or "cua-driver"
PRICE_PER_MTOK_INPUT = 0.042
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
ACTION = sys.argv[2] if len(sys.argv) > 2 else "set_value"

CANDIDATE_ROLES = {"button", "menuitem", "document", "tabitem", "edit"}
MAX_CANDIDATES = 12


def call(tool: str, payload: dict | None = None, timeout: int = 90) -> dict:
    cmd = [CUA, "call", tool] + ([json.dumps(payload)] if payload else [])
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", check=False,
        )
    except subprocess.TimeoutExpired:
        return {"_error": "timeout", "_ms": round((time.perf_counter() - t0) * 1000, 1)}
    dt = round((time.perf_counter() - t0) * 1000, 1)
    if proc.returncode != 0:
        return {"_error": (proc.stderr.strip() or proc.stdout.strip())[:400], "_ms": dt}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_error": f"non-JSON output: {proc.stdout[:200]!r}", "_ms": dt}
    if isinstance(data, dict):
        data["_ms"] = dt
        return data
    return {"_data": data, "_ms": dt}


def compact(snap: dict) -> list[dict]:
    """Filtered, small element state for Jev (no frames/actions — context rot!)."""
    return [
        {
            "i": e.get("element_index"),
            "role": e.get("role"),
            "label": e.get("label"),
            "value": e.get("value"),
            "enabled": e.get("enabled"),
            "token": e.get("element_token"),
        }
        for e in snap.get("elements", []) or []
    ]


def candidates(snap: dict) -> list[dict]:
    rows = [
        r for r in compact(snap)
        if str(r["role"]).lower() in CANDIDATE_ROLES and r["enabled"]
    ]
    return rows[:MAX_CANDIDATES]


def doc_value(snap: dict) -> str | None:
    return next(
        (
            e.get("value")
            for e in snap.get("elements", []) or []
            if str(e.get("role", "")).lower() == "document"
        ),
        None,
    )


def state_for_jev(snap: dict, token: str, note: str = "") -> dict:
    rows = compact(snap)
    status = next(
        (r["label"] for r in rows if "characters" in str(r.get("label", ""))), None
    )
    return {
        "goal": f"The document's full text content must become exactly: {token}",
        "window": snap.get("window_title") or snap.get("app_name"),
        "status_bar": status,
        "document_text": doc_value(snap),
        "controls": [
            {"i": r["i"], "role": r["role"], "label": r["label"]} for r in candidates(snap)
        ],
        "note": note,
    }


def jev_select(client: TypeSafeClient, snap: dict, token: str) -> tuple[str, float, dict]:
    criteria = {f"c{r['i']}": f"{r['role']} '{r['label']}'" for r in candidates(snap)}
    criteria["none_match"] = "No candidate can receive the text input"
    q = Choice(
        instructions=(
            "The next step is: set the document's full text content to the given token. "
            "Which candidate element is the input target that receives this text "
            "(the element that holds or accepts the document's text content)?"
        ),
        criteria=criteria,
    )
    t0 = time.perf_counter()
    resp = client.system_one(
        state=state_for_jev(snap, token, note="recent_actions: none yet this step"),
        questions={"select": q},
    )
    dt = (time.perf_counter() - t0) * 1000
    ans = resp.answers["select"]
    return ans.choice, ans.confidence, {"ms": dt, "tokens": resp.usage.input_tokens}


def jev_verify(client: TypeSafeClient, snap: dict, token: str) -> tuple[float, dict]:
    if ACTION == "set_value":
        instructions = (
            f"Is the document's full text content exactly '{token}' and nothing else?"
        )
    else:
        instructions = (
            f"Does the document's text content contain the text '{token}'?"
        )
    q = Noul(instructions=instructions)
    t0 = time.perf_counter()
    resp = client.system_one(state=state_for_jev(snap, token), questions={"done": q})
    dt = (time.perf_counter() - t0) * 1000
    return resp.answers["done"].noul, {"ms": dt, "tokens": resp.usage.input_tokens}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    client = TypeSafeClient()
    report: dict = {"n_iterations": N, "action": ACTION}
    tokens_total = 0

    launch = call("launch_app", {"name": "Notepad"})
    pid = launch.get("pid")
    wid = next((w.get("window_id") for w in launch.get("windows", []) or []), None)
    if not (pid and wid):
        wins = call("list_windows")
        wid = next(
            (w.get("window_id") for w in wins.get("_legacy_windows", []) or []
             if w.get("pid") == pid), None
        )
    report["launch_ms"] = launch.get("_ms")
    report["pid"], report["window_id"] = pid, wid
    time.sleep(1.2)

    iterations = []
    for i in range(N):
        token = f"eeze-loop-{i}-{uuid.uuid4().hex[:4]}"
        it: dict = {"i": i, "token": token}
        try:
            t_cycle = time.perf_counter()
            snap = call("get_window_state", {"pid": pid, "window_id": wid})
            it["capture1_ms"] = snap.get("_ms")

            choice, conf, sel_meta = jev_select(client, snap, token)
            tokens_total += sel_meta["tokens"]
            it["choice"] = choice
            it["choice_confidence"] = conf
            it["jev_select_ms"] = round(sel_meta["ms"], 1)

            token_map = {f"c{r['i']}": r["token"] for r in candidates(snap)}
            it["act"] = None
            if choice in token_map:
                if ACTION == "set_value":
                    act = call("set_value", {
                        "pid": pid, "window_id": wid,
                        "element_token": token_map[choice], "value": token,
                    })
                else:
                    act = call("type_text", {
                        "pid": pid, "window_id": wid,
                        "element_token": token_map[choice], "text": token,
                    })
                it["act"] = {
                    k: act.get(k) for k in ("effect", "route", "_ms", "_error")
                }
            else:
                it["act"] = {"skipped": f"choice {choice!r} not actionable"}

            time.sleep(0.3)
            snap2 = call("get_window_state", {"pid": pid, "window_id": wid})
            it["capture2_ms"] = snap2.get("_ms")
            dv = doc_value(snap2)
            it["doc_value"] = dv
            haystack = json.dumps(snap2.get("elements", [])) + (snap2.get("tree_markdown") or "")
            it["python_check"] = (dv == token) if ACTION == "set_value" else (token in haystack)
            it["status_bar"] = next(
                (e.get("label") for e in (snap2.get("elements") or [])
                 if "characters" in str(e.get("label", ""))), None
            )

            noul, ver_meta = jev_verify(client, snap2, token)
            tokens_total += ver_meta["tokens"]
            it["verify_noul"] = noul
            it["jev_verify_ms"] = round(ver_meta["ms"], 1)

            it["cycle_ms"] = round((time.perf_counter() - t_cycle) * 1000, 1)
            it["success"] = bool(it["python_check"] and noul >= 0.5)
            if i == N - 1 and snap2.get("screenshot_png_b64"):
                (OUT / "notepad_loop.png").write_bytes(
                    base64.b64decode(snap2["screenshot_png_b64"])
                )
        except Exception as exc:  # noqa: BLE001
            it["error"] = repr(exc)
            it["success"] = False
        iterations.append(it)
        print(json.dumps(it, default=str))

    kill = call("kill_app", {"pid": pid})
    report["iterations"] = iterations
    report["kill_ms"] = kill.get("_ms")

    cycles = [it["cycle_ms"] for it in iterations if "cycle_ms" in it]
    jev_lat = [
        it.get(k) for it in iterations for k in ("jev_select_ms", "jev_verify_ms")
        if it.get(k)
    ]
    ok = [it.get("success") for it in iterations]
    report["summary"] = {
        "success_rate": f"{sum(bool(x) for x in ok)}/{len(ok)}",
        "cycle_ms_p50": round(statistics.median(cycles), 1) if cycles else None,
        "cycle_ms_p95": round(sorted(cycles)[int(0.95 * (len(cycles) - 1))], 1) if cycles else None,
        "jev_calls_ms_p50": round(statistics.median(jev_lat), 1) if jev_lat else None,
        "jev_calls": len(jev_lat),
        "input_tokens_total": tokens_total,
        "cost_estimate_usd": round(tokens_total * PRICE_PER_MTOK_INPUT / 1e6, 7),
    }
    (OUT / "mini_loop_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print("SUMMARY: " + json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
