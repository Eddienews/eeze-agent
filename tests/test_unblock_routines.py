"""Fase 1 — routines must never freeze: abandon/expire approvals, reap orphaned runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.routines import RoutineStore, Scheduler


def _legacy_gate(db: Path, routine_id: str = "inv") -> tuple[RoutineStore, ApprovalStore, str, str]:
    """A routine parked on a pre-A2 approval: no digest, no run state (non-resumable)."""
    routines = RoutineStore(db)
    approvals = ApprovalStore(db)
    routines.add(routine_id, name="Invoices", kind="invoices",
                 schedule={"type": "daily", "at": "08:00"})
    approval_id = approvals.request(
        runset_id="rs-old", task=f"routine:{routine_id}", task_path="", agent_id="default",
        run_index=1, step_id="email-summary", step_index=0, action="email_summary",
        risk_class="external_send", reason="legacy", payload={}, action_digest=None,
    )
    run_id = routines.start_run(routine_id)
    routines.end_run(run_id, routine_id, status="needs_approval", approval_id=approval_id)
    return routines, approvals, approval_id, run_id


def test_legacy_approval_blocks_until_abandoned(tmp_path: Path):
    routines, approvals, approval_id, run_id = _legacy_gate(tmp_path / "e.db")
    assert routines.has_open_run("inv")

    row = approvals.abandon(approval_id, reason="old card")
    assert row["status"] == "abandoned"
    assert not routines.has_open_run("inv")
    assert routines.runs("inv")[0]["status"] == "abandoned"


def test_abandon_refuses_non_pending(tmp_path: Path):
    _r, approvals, approval_id, _ = _legacy_gate(tmp_path / "e.db")
    approvals.abandon(approval_id)
    try:
        approvals.abandon(approval_id)
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("second abandon must fail")


def test_pending_approvals_expire_after_ttl(tmp_path: Path):
    routines, approvals, approval_id, _ = _legacy_gate(tmp_path / "e.db")
    now = datetime.now(UTC)
    assert approvals.expire_stale(72, now=now) == []
    assert approvals.expire_stale(72, now=now + timedelta(hours=73)) == [approval_id]
    assert approvals.get(approval_id)["status"] == "expired"
    assert not routines.has_open_run("inv")
    assert approvals.expire_stale(0, now=now + timedelta(days=30)) == []  # 0 disables


def test_scheduler_tick_expires_and_spawns(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_APPROVAL_TTL_HOURS", "0.0001")
    db = tmp_path / "e.db"
    routines, approvals, approval_id, _ = _legacy_gate(db)
    with sqlite3.connect(db) as con:  # make the approval old and the routine due
        con.execute("UPDATE approvals SET created_at='2026-01-01T00:00:00+00:00'")
        con.execute("UPDATE routines SET next_run_at='2026-01-01T08:00:00'")
    spawned: list[list[str]] = []
    sched = Scheduler(routines, repo_root=tmp_path, home=tmp_path / "home",
                      spawn=lambda argv, **_: spawned.append(argv) or 1)
    assert sched.tick() == ["inv"]
    assert approvals.get(approval_id)["status"] == "expired"
    assert spawned == [["routines", "run", "inv"]]


def test_skipped_tick_is_logged(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_APPROVAL_TTL_HOURS", "0")
    db = tmp_path / "e.db"
    routines, _a, _id, _ = _legacy_gate(db)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE routines SET next_run_at='2026-01-01T08:00:00'")
    home = tmp_path / "home"
    sched = Scheduler(routines, repo_root=tmp_path, home=home, spawn=lambda *a, **k: 1)
    assert sched.tick() == []
    log = (home / "routines" / "run-inv.log").read_text(encoding="utf-8")
    assert "skipped" in log


def test_orphaned_running_rows_are_reaped(tmp_path: Path):
    routines = RoutineStore(tmp_path / "e.db")
    routines.add("r", name="R", kind="task", schedule={"type": "every", "minutes": 5})
    dead = routines.start_run("r", pid=999_999)
    live = routines.start_run("r", pid=4242)
    reaped = routines.reap_orphans(alive=lambda pid: pid == 4242)
    assert reaped == [dead]
    by_id = {r["id"]: r for r in routines.runs("r")}
    assert by_id[dead]["status"] == "error"
    assert by_id[dead]["detail"]["orphaned"] is True
    assert by_id[live]["status"] == "running"


def test_legacy_running_rows_without_pid_reaped_only_when_stale(tmp_path: Path):
    db = tmp_path / "e.db"
    routines = RoutineStore(db)
    routines.add("r", name="R", kind="task", schedule={"type": "every", "minutes": 5})
    run_id = routines.start_run("r")
    with sqlite3.connect(db) as con:
        con.execute("UPDATE routine_runs SET pid=NULL")
    now = datetime.now()  # noqa: DTZ005
    assert routines.reap_orphans(now=now, alive=lambda _p: False) == []
    assert routines.reap_orphans(now=now + timedelta(hours=13), alive=lambda _p: False) == [run_id]


def test_request_with_run_state_is_atomic(tmp_path: Path):
    approvals = ApprovalStore(tmp_path / "e.db")
    approval_id = approvals.request(
        runset_id="rs", task="t", task_path="", agent_id="default", run_index=1,
        step_id="s", step_index=0, action="a", risk_class="external_send", reason="r",
        action_digest="d" * 64, run_state=lambda aid: {"approval_id": aid, "x": 1},
    )
    state = approvals.run_state_for(approval_id)
    assert state is not None and json.loads(state["payload"]) == {"approval_id": approval_id, "x": 1}


def _client(tmp_path: Path) -> TestClient:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    (home / "api.token").write_text("tok-123", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "tok-123"}).status_code == 200
    return client


def test_api_abandon_works_on_non_resumable(tmp_path: Path, monkeypatch):
    db = tmp_path / "e.db"
    monkeypatch.setenv("EEZE_DB", str(db))
    _r, approvals, approval_id, _ = _legacy_gate(db)
    client = _client(tmp_path)
    headers = {"X-EEZE-Token": "tok-123"}
    refused = client.post(f"/api/approvals/{approval_id}/decide",
                          json={"decision": "approve"}, headers=headers)
    assert refused.status_code == 409
    ok = client.post(f"/api/approvals/{approval_id}/decide",
                     json={"decision": "abandon"}, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["approval"]["status"] == "abandoned"
    assert ok.json()["resumed"] is False


def test_grant_ttl_defaults_and_is_capped(tmp_path: Path):
    from pydantic import ValidationError

    from eeze_agent.api.schemas import GrantRequest

    assert GrantRequest().ttl_hours == 24
    try:
        GrantRequest(ttl_hours=24 * 365)
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("a year-long grant must be refused")


def test_cli_abandon(tmp_path: Path, monkeypatch, capsys):
    # Imported here, not at module level: importing the CLI loads the repo .env into
    # os.environ, which at collection time would leak real settings into every test.
    from eeze_agent.cli import main as cli_main

    db = tmp_path / "e.db"
    monkeypatch.setenv("EEZE_DB", str(db))
    _r, approvals, approval_id, _ = _legacy_gate(db)
    assert cli_main(["approvals", "list"]) == 0
    assert approval_id in capsys.readouterr().out
    assert cli_main(["approvals", "abandon", approval_id]) == 0
    assert approvals.get(approval_id)["status"] == "abandoned"
    assert cli_main(["approvals", "abandon", approval_id]) == 1


def test_health_reports_scheduler(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "e.db"))
    home = tmp_path / "home"
    home.mkdir()
    app = create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home)

    class _Sched:
        last_tick_at = "2026-09-26T08:00:00"

        def alive(self):
            return False

    app.state.scheduler = _Sched()
    body = TestClient(app).get("/api/health").json()
    assert body["service"] == "eeze"
    assert body["status"] == "degraded"
    assert body["scheduler"] == {"alive": False, "last_tick_at": "2026-09-26T08:00:00"}
