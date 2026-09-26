"""F4 — routines: store, schedule math, scheduler tick, invoices routine, gated send."""

from __future__ import annotations

import json
import smtplib
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pytest
from test_invoices import StubBrain, _stub_fields, _write_pdf

from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.routine_runner import run_resume, run_routine
from eeze_agent.core.routines import (
    RoutineStore,
    Scheduler,
    compute_next_run,
    spawn_detached,
    task_routine_status,
)

# ---------------- task status ----------------

@pytest.mark.parametrize(("summary", "expected"), [
    ({"status": "needs_approval", "success_rate": "0/0"}, "needs_approval"),
    ({"status": "done", "success_rate": "2/2", "success_rate_all_runs": "2/2",
      "runs_completed": 2, "task_runs": 2}, "ok"),
    ({"status": "done", "success_rate": "1/2", "success_rate_all_runs": "1/2"}, "error"),
    ({"status": "done", "success_rate": "1/1", "success_rate_all_runs": "1/2"}, "error"),
    ({"status": "done", "success_rate": "0/0"}, "error"),
    ({"status": "done", "success_rate": "1/1", "runs_completed": 1, "task_runs": 2}, "error"),
    ({"status": "error", "success_rate": "1/1"}, "error"),
])
def test_task_routine_status(summary: dict, expected: str):
    assert task_routine_status(summary) == expected


def test_task_routine_records_partial_failure_without_gui(tmp_path: Path, monkeypatch):
    from eeze_agent.agents.models import Agent
    from eeze_agent.core import routine_runner, tasks

    task_path = tmp_path / "task.yaml"
    task_path.write_text("test", encoding="utf-8")
    monkeypatch.setattr(tasks, "load_task", lambda _path: object())
    monkeypatch.setattr(routine_runner, "run_set", lambda **_kw: {
        "status": "done", "success_rate": "1/2", "success_rate_all_runs": "1/2",
        "runs_completed": 2, "task_runs": 2,
    })
    result = routine_runner.run_task(
        {"id": "t1", "params": {"task_path": str(task_path)}},
        repo_root=tmp_path, approvals=ApprovalStore(tmp_path / "r.db"),
        agent=Agent(id="default", name="Default"), log=tmp_path / "run.log",
        brain=object(),
    )
    assert result["status"] == "error"
    assert result["summary"]["success_rate"] == "1/2"


# ---------------- schedule math ----------------

def test_compute_next_run():
    # local wall-clock by design (routines follow business hours)
    base = datetime(2026, 9, 18, 7, 0, 0)  # noqa: DTZ001
    assert compute_next_run({"type": "every", "minutes": 30}, base) == "2026-09-18T07:30:00"
    assert compute_next_run({"type": "daily", "at": "08:00"}, base) == "2026-09-18T08:00:00"
    assert compute_next_run({"type": "daily", "at": "06:00"}, base) == "2026-09-19T06:00:00"
    with pytest.raises(ValueError):
        compute_next_run({"type": "cron", "expr": "* * * * *"}, base)
    with pytest.raises(ValueError):
        compute_next_run({"type": "daily", "at": "8h"}, base)


# ---------------- store ----------------

def test_store_crud_and_runs(tmp_path: Path):
    store = RoutineStore(tmp_path / "r.db")
    row = store.add("inv", name="Invoices", kind="invoices", schedule={"type": "every", "minutes": 60})
    assert row["enabled"] is True and row["next_run_at"]
    assert [r["id"] for r in store.list()] == ["inv"]
    store.add("inv", name="Invoices v2", kind="invoices", schedule={"type": "daily", "at": "08:00"})
    assert store.get("inv")["name"] == "Invoices v2"
    assert store.set_enabled("inv", False) and store.get("inv")["enabled"] is False
    run_id = store.start_run("inv")
    store.end_run(run_id, "inv", status="ok", detail={"x": 1})
    runs = store.runs("inv")
    assert runs[0]["status"] == "ok" and runs[0]["detail"] == {"x": 1}
    assert store.remove("inv") and store.get("inv") is None


def test_scheduler_spawns_due_and_advances(tmp_path: Path):
    store = RoutineStore(tmp_path / "r.db")
    store.add("r1", name="R", kind="invoices", schedule={"type": "every", "minutes": 1})
    spawned: list = []
    sched = Scheduler(
        store, repo_root=tmp_path, home=tmp_path,
        spawn=lambda argv, cwd, log_path: spawned.append(list(argv)),
    )
    t0 = datetime.now()  # noqa: DTZ005
    assert sched.tick(now=t0 + timedelta(minutes=2)) == ["r1"]
    assert spawned == [["routines", "run", "r1"]]
    assert sched.tick(now=t0 + timedelta(minutes=2)) == []  # next_run advanced
    assert sched.tick(now=t0 + timedelta(minutes=4)) == ["r1"]
    assert len(spawned) == 2


def test_scheduler_records_spawn_failure_without_a_hot_loop(tmp_path: Path):
    store = RoutineStore(tmp_path / "r.db")
    schedule = {"type": "every", "minutes": 1}
    store.add("r1", name="R", kind="invoices", schedule=schedule)
    attempts = []

    def unavailable(argv, *, cwd, log_path):
        attempts.append(list(argv))
        raise OSError(2, "process unavailable")

    sched = Scheduler(store, repo_root=tmp_path, home=tmp_path, spawn=unavailable)
    now = datetime.now() + timedelta(minutes=2)  # noqa: DTZ005
    assert sched.tick(now=now) == []
    runs = store.runs("r1")
    assert len(runs) == 1
    assert runs[0]["status"] == "error" and runs[0]["ended_at"]
    assert runs[0]["approval_id"] is None
    assert runs[0]["detail"] == {"spawn_failure": {"type": "FileNotFoundError", "errno": 2}}
    assert store.get("r1")["last_status"] == "error"
    assert store.get("r1")["next_run_at"] == compute_next_run(schedule, now)
    assert sched.tick(now=now) == []
    assert len(attempts) == 1 and len(store.runs("r1")) == 1
    assert sched.tick(now=now + timedelta(minutes=2)) == []
    assert len(attempts) == 2 and len(store.runs("r1")) == 2


def test_spawn_detached_closes_log_on_popen_error(tmp_path: Path, monkeypatch):
    from eeze_agent.core import routines

    opened = []

    def unavailable(argv, **kwargs):
        opened.append(kwargs["stdout"])
        raise OSError(2, "cannot start")

    monkeypatch.setattr(routines.subprocess, "Popen", unavailable)
    with pytest.raises(OSError):
        spawn_detached(["routines", "run", "r1"], cwd=tmp_path, log_path=tmp_path / "run.log")
    assert len(opened) == 1 and opened[0].closed


def test_scheduler_logs_unhandled_tick_errors_and_keeps_polling(tmp_path: Path, monkeypatch, caplog):
    store = RoutineStore(tmp_path / "r.db")
    sched = Scheduler(store, repo_root=tmp_path, home=tmp_path, interval_s=0.01)
    recovered = threading.Event()
    attempts: list[int] = []

    def flaky_tick():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("sensitive private text")
        recovered.set()
        return []

    monkeypatch.setattr(sched, "tick", flaky_tick)
    with caplog.at_level("ERROR", logger="eeze.routines"):
        try:
            sched.start()
            assert recovered.wait(2), "scheduler thread did not resume after the failed tick"
        finally:
            sched.stop()
            if sched._thread is not None:
                sched._thread.join(timeout=2)
    assert len(attempts) >= 2
    assert "scheduler tick failed: RuntimeError" in caplog.text
    assert "sensitive private text" not in caplog.text
    assert store.runs() == []


def test_scheduler_skips_routines_with_open_runs(tmp_path: Path):
    store = RoutineStore(tmp_path / "r.db")
    approvals = ApprovalStore(tmp_path / "r.db")
    store.add("r1", name="R", kind="invoices", schedule={"type": "every", "minutes": 1})
    spawned: list = []
    sched = Scheduler(
        store, repo_root=tmp_path, home=tmp_path,
        spawn=lambda argv, cwd, log_path: spawned.append(list(argv)),
    )
    t0 = datetime.now()  # noqa: DTZ005

    run_id = store.start_run("r1")  # a run is in flight
    assert sched.tick(now=t0 + timedelta(minutes=2)) == []
    assert store.get("r1")["next_run_at"] > (t0 + timedelta(minutes=2)).isoformat()  # postponed

    store.end_run(run_id, "r1", status="ok")
    assert sched.tick(now=t0 + timedelta(minutes=4)) == ["r1"]

    # needs_approval with a still-pending approval also blocks stacking
    run2 = store.start_run("r1")
    ap_id = approvals.request(
        runset_id="x", task="routine:r1", task_path="", agent_id="default", run_index=1,
        step_id="email-summary", step_index=0, action="email_summary",
        risk_class="external_send", reason="x", payload={},
    )
    store.end_run(run2, "r1", status="needs_approval", approval_id=ap_id)
    assert store.has_open_run("r1") is True
    assert sched.tick(now=t0 + timedelta(minutes=6)) == []

    approvals.decide(ap_id, "approve")
    assert store.has_open_run("r1") is False
    assert sched.tick(now=t0 + timedelta(minutes=8)) == ["r1"]


# ---------------- invoices routine ----------------

def _fake_pull(monkeypatch):
    from eeze_agent.verticals.invoices import imap_source

    def fake_pull(out_dir, search="ALL", **_kw):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = out_dir / "a.pdf"
        _write_pdf(pdf, ["Acme Ltda", "Invoice No: INV-1", "Total: EUR 100,00", "Due date: 10/10/2026"])
        return imap_source.PullResult(
            host="fake", folder="INBOX", search=search, fetched=1, attachments=1, files=[str(pdf)]
        )

    monkeypatch.setattr(imap_source, "pull_pdf_attachments", fake_pull)


def test_invoices_routine_gated_email(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    _fake_pull(monkeypatch)
    repo = tmp_path / "repo"
    store = RoutineStore()
    store.add(
        "inv1", name="Faturas", kind="invoices", schedule={"type": "every", "minutes": 60},
        params={"email_summary": True, "email_to": "dest@example.com"},
    )
    brain = StubBrain(_stub_fields("2026-10-10", "Due date: 10/10/2026"))
    result = run_routine("inv1", repo_root=repo, home=tmp_path / "home", brain=brain)

    assert result["status"] == "needs_approval"
    approval_id = result["approval_id"]
    assert approval_id
    approvals = ApprovalStore()
    row = approvals.get(approval_id)
    assert row and row["risk_class"] == "external_send" and row["status"] == "pending"
    state = approvals.run_state_for(approval_id)
    payload = json.loads(state["payload"])
    assert payload["resume_argv"] == ["routines", "resume", approval_id]
    out_dir = Path(result["out_dir"])
    assert (out_dir / "ledger.csv").exists() and (out_dir / "anomalies.md").exists()
    assert result["ledger"]["files"] == 1
    assert store.runs("inv1")[0]["status"] == "needs_approval"


class FakeSMTP:
    sent: ClassVar[dict] = {}
    send_count: ClassVar[int] = 0

    def __init__(self, host, port, timeout=None):
        FakeSMTP.sent["host"] = (host, port)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        FakeSMTP.sent["login"] = (user, password)

    def send_message(self, message):
        FakeSMTP.send_count += 1
        FakeSMTP.sent["message"] = message


def _seed_routine_state(tmp_path: Path, monkeypatch, *, email_to: str = "dest@example.com") -> tuple[ApprovalStore, str, Path]:
    _fake_pull(monkeypatch)
    store = RoutineStore()
    store.add("inv1", name="Faturas", kind="invoices", schedule={"type": "every", "minutes": 60},
              params={"email_summary": True, "email_to": email_to})
    result = run_routine("inv1", repo_root=tmp_path, home=tmp_path / "home",
                         brain=StubBrain(_stub_fields("2026-10-10", "Due date: 10/10/2026")))
    assert result["status"] == "needs_approval"
    return ApprovalStore(), result["approval_id"], Path(result["out_dir"])


def test_routine_resume_requires_approval_then_sends(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    monkeypatch.setenv("EEZE_IMAP_USER", "sender@example.com")
    monkeypatch.setenv("EEZE_IMAP_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent = {}
    FakeSMTP.send_count = 0
    approvals, approval_id, _ = _seed_routine_state(tmp_path, monkeypatch)
    log = tmp_path / "resume.log"

    denied = run_resume(approval_id, repo_root=tmp_path, approvals=approvals, log=log)
    assert denied["status"] == "error"  # not approved yet
    assert "message" not in FakeSMTP.sent

    approvals.decide(approval_id, "approve")
    result = run_resume(approval_id, repo_root=tmp_path, approvals=approvals, log=log)
    assert result["status"] == "ok" and result["email"]["sent"] is True
    assert FakeSMTP.sent["login"][0] == "sender@example.com"
    assert FakeSMTP.sent["login"][1] == "abcdefghijklmnop"  # spaces stripped
    message = FakeSMTP.sent["message"]
    assert message["To"] == "dest@example.com"
    attachments = [part.get_filename() for part in message.walk() if part.get_filename()]
    assert "ledger.csv" in attachments
    # the original routine run record is closed as ok by the resume
    assert RoutineStore().runs("inv1")[0]["status"] == "ok"
    assert run_resume(approval_id, repo_root=tmp_path, approvals=approvals, log=log)["status"] == "error"
    assert FakeSMTP.send_count == 1


def test_invoice_approval_is_resumable_in_api(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient

    from eeze_agent.api.app import create_app

    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    approvals, approval_id, _ = _seed_routine_state(tmp_path, monkeypatch)
    assert approvals.get(approval_id)["action_digest"]
    home = tmp_path / "operator"
    home.mkdir()
    (home / "api.token").write_text("test-token", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "test-token"}).status_code == 200
    items = client.get("/api/approvals", params={"status": "pending"}).json()["items"]
    assert next(item for item in items if item["id"] == approval_id)["resumable"] is True


@pytest.mark.parametrize("change", ["recipient", "params", "ledger", "missing_report"])
def test_invoice_resume_refuses_changed_action(tmp_path: Path, monkeypatch, change: str):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    monkeypatch.setenv("EEZE_IMAP_USER", "sender@example.com")
    monkeypatch.setenv("EEZE_IMAP_APP_PASSWORD", "fake-secret")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent = {}
    FakeSMTP.send_count = 0
    approvals, approval_id, out = _seed_routine_state(tmp_path, monkeypatch)
    if change in {"recipient", "params"}:
        params = {"email_summary": True, "email_to": "dest@example.com"}
        if change == "recipient":
            params["email_to"] = "other@example.com"
        else:
            params["search"] = "UNSEEN"
        RoutineStore().add("inv1", name="Faturas", kind="invoices",
                           schedule={"type": "every", "minutes": 60}, params=params)
    elif change == "ledger":
        (out / "ledger.csv").write_bytes(b"changed after approval")
    else:
        (out / "anomalies.md").unlink()
    approvals.decide(approval_id, "approve")
    result = run_resume(approval_id, repo_root=tmp_path, approvals=approvals, log=tmp_path / "resume.log")
    assert result["status"] == "error"
    assert FakeSMTP.send_count == 0
    assert approvals.run_state_for(approval_id)["status"] == "waiting"


def test_legacy_invoice_resume_does_not_send(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    monkeypatch.setenv("EEZE_IMAP_USER", "sender@example.com")
    monkeypatch.setenv("EEZE_IMAP_APP_PASSWORD", "fake-secret")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent = {}
    FakeSMTP.send_count = 0
    approvals, approval_id, _ = _seed_routine_state(tmp_path, monkeypatch)
    with approvals._connect() as con:
        con.execute("UPDATE approvals SET action_digest=NULL WHERE id=?", (approval_id,))
    approvals.decide(approval_id, "approve")  # legacy CLI decision; API blocks this
    result = run_resume(approval_id, repo_root=tmp_path, approvals=approvals, log=tmp_path / "resume.log")
    assert result["status"] == "error"
    assert FakeSMTP.send_count == 0


def test_invoice_failed_send_is_consumed_not_retried(tmp_path: Path, monkeypatch):
    class UncertainSMTP(FakeSMTP):
        def send_message(self, message):
            super().send_message(message)
            raise ConnectionResetError("status unknown")

    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    monkeypatch.setenv("EEZE_IMAP_USER", "sender@example.com")
    monkeypatch.setenv("EEZE_IMAP_APP_PASSWORD", "fake-secret")
    monkeypatch.setattr(smtplib, "SMTP_SSL", UncertainSMTP)
    FakeSMTP.send_count = 0
    approvals, approval_id, _ = _seed_routine_state(tmp_path, monkeypatch)
    approvals.decide(approval_id, "approve")
    log = tmp_path / "resume.log"
    first = run_resume(approval_id, repo_root=tmp_path, approvals=approvals, log=log)
    assert first["status"] == "error"
    assert approvals.run_state_for(approval_id)["status"] == "resumed"
    assert RoutineStore().runs("inv1")[0]["status"] == "error"
    assert run_resume(approval_id, repo_root=tmp_path, approvals=approvals, log=log)["status"] == "error"
    assert FakeSMTP.send_count == 1


def test_invoice_resume_rejects_modified_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    monkeypatch.setenv("EEZE_IMAP_USER", "sender@example.com")
    monkeypatch.setenv("EEZE_IMAP_APP_PASSWORD", "fake-secret")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.send_count = 0
    approvals, approval_id, _ = _seed_routine_state(tmp_path, monkeypatch)
    state = approvals.run_state_for(approval_id)
    payload = json.loads(state["payload"])
    payload["completed"]["ledger"]["files"] = 999
    with approvals._connect() as con:
        con.execute("UPDATE run_states SET payload=? WHERE id=?", (json.dumps(payload), state["id"]))
    approvals.decide(approval_id, "approve")
    result = run_resume(approval_id, repo_root=tmp_path, approvals=approvals, log=tmp_path / "resume.log")
    assert result["status"] == "error"
    assert FakeSMTP.send_count == 0


def test_routine_allow_sends_directly(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    monkeypatch.setenv("EEZE_IMAP_USER", "sender@example.com")
    monkeypatch.setenv("EEZE_IMAP_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent = {}
    _fake_pull(monkeypatch)
    repo = tmp_path / "repo"
    store = RoutineStore()
    store.add(
        "inv2", name="Faturas", kind="invoices", schedule={"type": "every", "minutes": 60},
        params={"email_summary": True, "email_to": "dest@example.com", "allow": ["external_send"]},
    )
    brain = StubBrain(_stub_fields("2026-10-10", "Due date: 10/10/2026"))
    result = run_routine("inv2", repo_root=repo, home=tmp_path / "home", brain=brain)
    assert result["status"] == "ok"
    assert result["email"]["sent"] is True
    assert ApprovalStore().count(status="pending") == 0  # nothing was gated


def test_task_routine_records_error_for_missing_task(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    store = RoutineStore()
    store.add("t1", name="T", kind="task", schedule={"type": "every", "minutes": 60},
              params={"task_path": str(tmp_path / "nope.yaml")})
    result = run_routine("t1", repo_root=tmp_path / "repo", home=tmp_path / "home")
    assert result["status"] == "error"
    assert "not found" in result["error"]
    assert store.runs("t1")[0]["status"] == "error"
