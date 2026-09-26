"""F6 — weekly report: aggregation from journals/store/audits, markdown rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.report import build_report, render_markdown
from eeze_agent.core.routines import RoutineStore

BASE = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
NOW = BASE + timedelta(hours=1)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _seed_runs(repo: Path) -> None:
    now_ts = BASE.isoformat()
    old_ts = (BASE - timedelta(days=30)).isoformat()
    runs = repo / "artifacts" / "runs"
    _write(
        runs / "rs-now" / "journal.jsonl",
        "\n".join(
            json.dumps(e)
            for e in [
                {"kind": "runset_start", "ts": now_ts, "task": "t1"},
                {"kind": "run_end", "ts": now_ts, "run_index": 1, "ok": True, "cycle_ms": 100},
                {"kind": "runset_end", "ts": now_ts, "status": "done"},
            ]
        ),
    )
    _write(runs / "rs-now" / "summary.json", json.dumps({
        "success_rate": "1/1", "cost_estimate_usd": 0.0002, "jev_calls": 3, "input_tokens_total": 4718,
    }))
    _write(
        runs / "rs-intr" / "journal.jsonl",
        "\n".join(
            json.dumps(e)
            for e in [
                {"kind": "runset_start", "ts": now_ts, "task": "t2"},
                {"kind": "step_end", "ts": now_ts, "run_index": 1, "step_id": "s1", "interference": True},
                {"kind": "run_end", "ts": now_ts, "run_index": 1, "ok": True},
            ]
        ),
    )
    _write(
        runs / "rs-old" / "journal.jsonl",
        "\n".join(
            json.dumps(e)
            for e in [
                {"kind": "runset_start", "ts": old_ts, "task": "old"},
                {"kind": "run_end", "ts": old_ts, "run_index": 1, "ok": True},
            ]
        ),
    )


def _seed_audit(repo: Path) -> None:
    _write(repo / "artifacts" / "audits" / "focus-1.json", json.dumps({"at": BASE.isoformat(), "pass": True}))


def test_build_report_and_render(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    _seed_runs(tmp_path)
    _seed_audit(tmp_path)

    store = RoutineStore()
    store.add("inv", name="Invoices", kind="invoices", schedule={"type": "daily", "at": "08:00"})
    run_id = store.start_run("inv")
    store.end_run(run_id, "inv", status="ok", detail={"ledger": {"files": 5, "ok": 1, "flagged": 4, "anomalies": 4}})
    run_id2 = store.start_run("inv")
    store.end_run(run_id2, "inv", status="needs_approval", approval_id=None)

    approvals = ApprovalStore()
    ap1 = approvals.request(
        runset_id="x", task="t", task_path="", agent_id="default", run_index=1,
        step_id="s", step_index=0, action="a", risk_class="external_send", reason="r", payload={},
    )
    approvals.decide(ap1, "approve")
    approvals.request(
        runset_id="y", task="t", task_path="", agent_id="default", run_index=1,
        step_id="s", step_index=0, action="a", risk_class="install_exec", reason="r", payload={},
    )

    report = build_report(repo_root=tmp_path, days=7, now=NOW)
    totals = report["runs"]["totals"]
    assert totals["runs"] == 2 and totals["ok"] == 1 and totals["interference"] == 1
    assert totals["success_rate"] == "1/2"
    assert totals["cost_usd"] == 0.0002 and totals["jev_calls"] == 3
    assert totals["cost_missing_runsets"] == 1  # rs-intr has no summary
    assert [d["date"] for d in report["runs"]["by_day"]] == ["2026-09-18"]
    assert report["runs"]["by_day"][0]["cost_usd"] == 0.0002  # runset cost attributed to its day

    assert report["routines"]["total_runs"] == 2
    assert report["routines"]["flagged_files"] == 4 and report["routines"]["anomalies"] == 4
    assert report["routines"]["by_status"] == {"ok": 1, "needs_approval": 1}

    assert report["approvals"]["decided"] == 1 and report["approvals"]["approved"] == 1
    assert report["approvals"]["pending_now"] == 1

    assert report["audits"]["total"] == 1 and report["audits"]["pass"] == 1

    warnings = " | ".join(report["warnings"])
    assert "waiting on you" in warnings
    assert "cost unavailable for 1" in warnings

    text = render_markdown(report)
    assert "## Task runs" in text and "## Routines" in text and "## Approvals" in text
    assert "| 2026-09-18 | 2 | 1 | 0 | 1 |" in text
    assert "FOCUS" not in text  # focus section is audit stats, not the raw name
    assert "pass: 1" in text


def test_report_empty_tree_is_honest(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    report = build_report(repo_root=tmp_path, days=7, now=NOW)
    assert report["runs"]["totals"]["runs"] == 0
    assert report["runs"]["totals"]["success_rate"] is None
    assert any("no task runs" in w for w in report["warnings"])
    text = render_markdown(report)
    assert "unavailable" in text


def test_old_runsets_excluded(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    _seed_runs(tmp_path)
    report = build_report(repo_root=tmp_path, days=7, now=NOW)
    assert all("rs-old" not in json.dumps(d) for d in report["runs"]["by_day"])
    assert report["runs"]["totals"]["runs"] == 2  # rs-old filtered out
