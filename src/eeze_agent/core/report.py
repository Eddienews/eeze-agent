"""Weekly metrics report (F6): runs, routines, approvals, audits — from local artifacts.

Everything is read from what already exists on this machine: run journals and summaries
(``artifacts/runs/``), routine run records (``~/.eeze/eeze.db``), approvals/grants, and
focus-audit artifacts (``artifacts/audits/``). Missing data is reported as ``None``/counts,
never invented — a cost that is not recorded is listed as a warning, not as zero.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _iter_journal(path: Path):
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def collect_runs(runs_root: Path, cutoff: datetime) -> dict:
    """Aggregate run journals/summaries with a run_end at/after ``cutoff``."""
    totals = {"runs": 0, "ok": 0, "failed": 0, "interference": 0, "cost_usd": 0.0,
              "jev_calls": 0, "tokens": 0, "cost_missing_runsets": 0}
    by_day: dict[str, dict] = {}
    if not runs_root.exists():
        return {"totals": totals, "by_day": [], "runsets": 0}

    runsets = 0
    for runset in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        journal = list(_iter_journal(runset / "journal.jsonl"))
        if not journal:
            continue
        interfered: set = set()
        for event in journal:
            if event.get("kind") == "step_end" and event.get("interference"):
                interfered.add(event.get("run_index"))
            if event.get("kind") == "run_error" and event.get("error") == "external_input_detected":
                interfered.add(event.get("run_index"))
        ended = [
            event
            for event in journal
            if event.get("kind") == "run_end" and (_parse_iso(event.get("ts")) or cutoff) >= cutoff
        ]
        if not ended:
            continue
        runsets += 1
        runset_days: list[str] = []
        for event in ended:
            day = (event.get("ts") or "")[:10]
            runset_days.append(day)
            bucket = by_day.setdefault(day, {"date": day, "runs": 0, "ok": 0, "failed": 0,
                                             "interference": 0, "cost_usd": 0.0})
            interference = event.get("run_index") in interfered or event.get("error") == "external_input_detected"
            ok = bool(event.get("ok")) and not interference
            totals["runs"] += 1
            bucket["runs"] += 1
            if interference:
                totals["interference"] += 1
                bucket["interference"] += 1
            elif ok:
                totals["ok"] += 1
                bucket["ok"] += 1
            else:
                totals["failed"] += 1
                bucket["failed"] += 1
        summary = _load_json(runset / "summary.json")
        if summary:
            cost = summary.get("cost_estimate_usd")
            if cost is None:
                totals["cost_missing_runsets"] += 1
            else:
                totals["cost_usd"] += float(cost)
                # attribute the runset cost to its latest run day so the daily table sums
                by_day[runset_days[-1]]["cost_usd"] = round(
                    by_day[runset_days[-1]]["cost_usd"] + float(cost), 6
                )
            totals["jev_calls"] += int(summary.get("jev_calls") or 0)
            totals["tokens"] += int(summary.get("input_tokens_total") or 0)
        else:
            totals["cost_missing_runsets"] += 1
    ordered = [by_day[key] for key in sorted(by_day)]
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    return {"totals": totals, "by_day": ordered, "runsets": runsets}


def collect_routines(home: Path, cutoff_local: datetime) -> dict:
    from eeze_agent.core.routines import RoutineStore

    store = RoutineStore()
    rows = [r for r in store.runs(None, limit=500) if (_parse_iso_local(r["started_at"]) or cutoff_local) >= cutoff_local]
    by_status: dict[str, int] = {}
    flagged = 0
    anomalies = 0
    per_routine: dict[str, dict] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        ledger = (row.get("detail") or {}).get("ledger") or {}
        flagged += int(ledger.get("flagged") or 0)
        anomalies += int(ledger.get("anomalies") or 0)
        item = per_routine.setdefault(row["routine_id"], {"routine_id": row["routine_id"], "runs": 0,
                                                          "last_status": None, "last_at": None})
        item["runs"] += 1
        if item["last_at"] is None or (row.get("started_at") or "") > item["last_at"]:
            item["last_at"] = row.get("started_at")
            item["last_status"] = status
    return {
        "total_runs": len(rows),
        "by_status": by_status,
        "flagged_files": flagged,
        "anomalies": anomalies,
        "items": [per_routine[key] for key in sorted(per_routine)],
    }


def _parse_iso_local(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone()
    except ValueError:
        return None


def collect_approvals(cutoff: datetime) -> dict:
    from eeze_agent.core.approvals import ApprovalStore

    store = ApprovalStore()
    rows = store.list(limit=500)
    decided = approved = denied = 0
    for row in rows:
        when = _parse_iso(row.get("decided_at") or row.get("created_at"))
        if row.get("status") != "pending" and when and when >= cutoff:
            decided += 1
            approved += 1 if row.get("status") == "approved" else 0
            denied += 1 if row.get("status") == "denied" else 0
    grants = [g for g in store.list_grants(include_revoked=True) if getattr(g, "get", None)]
    grants_active = 0
    now = datetime.now(UTC)
    for grant in grants:
        if grant.get("revoked_at"):
            continue
        expires = _parse_iso(grant.get("expires_at"))
        if expires is None or expires >= now:
            grants_active += 1
    return {
        "decided": decided,
        "approved": approved,
        "denied": denied,
        "pending_now": store.count(status="pending"),
        "grants_active": grants_active,
    }


def collect_audits(repo_root: Path, cutoff: datetime) -> dict:
    audits_dir = repo_root / "artifacts" / "audits"
    total = passed = 0
    last: dict | None = None
    if audits_dir.exists():
        for path in sorted(audits_dir.glob("focus-*.json")):
            data = _load_json(path)
            when = _parse_iso(data.get("at"))
            if when is None or when < cutoff:
                continue
            total += 1
            passed += 1 if data.get("pass") is True else 0
            last = {"artifact": str(path), "pass": bool(data.get("pass")), "at": data.get("at")}
    return {"total": total, "pass": passed, "fail": total - passed, "last": last}


def build_report(*, repo_root: Path, days: int = 7, now: datetime | None = None) -> dict:
    now_utc = now or datetime.now(UTC)
    cutoff = now_utc - timedelta(days=days)
    cutoff_local = datetime.now().astimezone() - timedelta(days=days)

    runs = collect_runs(repo_root / "artifacts" / "runs", cutoff)
    routines = collect_routines(repo_root, cutoff_local)
    approvals = collect_approvals(cutoff)
    audits = collect_audits(repo_root, cutoff)

    warnings: list[str] = []
    totals = runs["totals"]
    if totals["runs"]:
        totals["success_rate"] = f"{totals['ok']}/{totals['runs']}"
    else:
        totals["success_rate"] = None
        warnings.append("no task runs in the window")
    if totals["interference"]:
        warnings.append(f"{totals['interference']} interference run(s) — see the journals")
    if totals["cost_missing_runsets"]:
        warnings.append(
            f"cost unavailable for {totals['cost_missing_runsets']} runset(s) (no recorded usage — not zero)"
        )
    if approvals["pending_now"]:
        warnings.append(f"{approvals['pending_now']} approval(s) waiting on you")
    for item in routines["items"]:
        if item["last_status"] == "error":
            warnings.append(f"routine {item['routine_id']} last run errored")

    return {
        "generated_at": now_utc.isoformat(timespec="seconds"),
        "window_days": days,
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "runs": runs,
        "routines": routines,
        "approvals": approvals,
        "audits": audits,
        "warnings": warnings,
    }


def render_markdown(report: dict) -> str:
    runs = report["runs"]["totals"]
    routines = report["routines"]
    approvals = report["approvals"]
    audits = report["audits"]
    lines = [
        f"# Eeze — weekly report ({report['window_days']} days)",
        "",
        f"_Generated {report['generated_at']} · window starts {report['cutoff']}_",
        "",
        "## Task runs",
        "",
        f"- runs: **{runs['runs']}** · ok: {runs['ok']} · failed: {runs['failed']} · interference: {runs['interference']}",
        f"- success rate: {runs['success_rate'] or 'unavailable'}",
        f"- cost (recorded): ${runs['cost_usd']:.6f} · Jev calls: {runs['jev_calls']} · tokens: {runs['tokens']}",
        "",
        "| day | runs | ok | failed | interference | cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for day in report["runs"]["by_day"]:
        lines.append(
            f"| {day['date']} | {day['runs']} | {day['ok']} | {day['failed']} | "
            f"{day['interference']} | ${day['cost_usd']:.6f} |"
        )
    if not report["runs"]["by_day"]:
        lines.append("| — | — | — | — | — | — |")
    lines += [
        "",
        "## Routines",
        "",
        f"- runs: **{routines['total_runs']}** · flagged files: {routines['flagged_files']} · anomalies: {routines['anomalies']}",
    ]
    for item in routines["items"]:
        lines.append(f"- `{item['routine_id']}`: {item['runs']} run(s), last = {item['last_status']} ({item['last_at']})")
    lines += [
        "",
        "## Approvals",
        "",
        f"- decided: {approvals['decided']} (approved {approvals['approved']} · denied {approvals['denied']})",
        f"- waiting now: **{approvals['pending_now']}** · active grants: {approvals['grants_active']}",
        "",
        "## Focus audits",
        "",
        f"- audits: {audits['total']} · pass: {audits['pass']} · fail: {audits['fail']}",
    ]
    if audits["last"]:
        lines.append(
            f"- last: {'PASS' if audits['last']['pass'] else 'FAIL'} — {audits['last']['artifact']}"
        )
    lines += ["", "## Warnings", ""]
    lines += [f"- {w}" for w in report["warnings"]] or ["- none"]
    lines.append("")
    return "\n".join(lines)
