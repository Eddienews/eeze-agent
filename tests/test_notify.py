"""Desktop notifications: toast builder, dedup watcher, toggle endpoint."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.notify import ApprovalWatcher, RoutineFailureWatcher, approval_body, toast
from eeze_agent.core.routines import RoutineStore
from eeze_agent.core.settings import SettingsStore


class OkProc:
    returncode = 0
    stderr = b""


class BadProc:
    returncode = 1
    stderr = b"boom"


def test_toast_builds_escaped_xml_and_never_raises(monkeypatch):
    captured: dict = {}

    def runner(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return OkProc()

    monkeypatch.setattr("eeze_agent.core.notify.sys.platform", "win32")
    monkeypatch.setattr("eeze_agent.core.notify._powershell", lambda: "powershell")
    assert toast("T & <x>", "body", runner=runner) is True
    xml = base64.b64decode(captured["env"]["EEZE_TOAST_XML"]).decode("utf-8")
    assert "<text>T &amp; &lt;x&gt;</text>" in xml and "<text>body</text>" in xml
    assert captured["cmd"][1] == "-NoProfile"

    monkeypatch.setattr("eeze_agent.core.notify.sys.platform", "win32")
    assert toast("t", "b", runner=lambda *a, **k: BadProc()) is False

    def raising(*_a, **_k):
        raise OSError("no powershell")

    assert toast("t", "b", runner=raising) is False


def test_toast_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr("eeze_agent.core.notify.sys.platform", "linux")
    assert toast("t", "b", runner=lambda *a, **k: OkProc()) is False


def test_approval_body_names_agent_step_and_risk():
    body = approval_body(
        {"agent_id": "finance", "step_id": "send-ledger", "risk_class": "external_send"}
    )
    assert "finance" in body and "send-ledger" in body and "external_send" in body
    assert "approvals" in body


def _request(store: ApprovalStore, step: str) -> str:
    return store.request(
        runset_id=f"rs-{step}",
        task="t",
        task_path="tasks/notepad-gated-demo.yaml",
        agent_id="ops",
        run_index=0,
        step_id=step,
        step_index=0,
        action="click",
        risk_class="write_local",
        reason="",
    )


def _watcher(tmp_path: Path, calls: list):
    store = ApprovalStore(tmp_path / "a.db")
    settings = SettingsStore(tmp_path / "a.db")
    watcher = ApprovalWatcher(
        store, settings, notifier=lambda title, body: (calls.append((title, body)), True)[1]
    )
    return store, settings, watcher


def test_watcher_toasts_new_pending_once_and_dedupes(tmp_path: Path):
    calls: list = []
    store, settings, watcher = _watcher(tmp_path, calls)
    first = _request(store, "one")
    assert watcher.tick() == [first]
    assert watcher.tick() == []  # already toasted
    second = _request(store, "two")
    assert watcher.tick() == [second]
    assert len(calls) == 2

    # restart: the dedup lives in the settings table
    restarted = ApprovalWatcher(
        store, settings, notifier=lambda t, b: (calls.append((t, b)), True)[1]
    )
    assert restarted.tick() == []
    assert len(calls) == 2


def test_watcher_disabled_by_setting(tmp_path: Path):
    calls: list = []
    store, settings, watcher = _watcher(tmp_path, calls)
    settings.set("notify_approvals", "0")
    _request(store, "one")
    assert watcher.tick() == []
    assert calls == []
    settings.set("notify_approvals", "1")
    assert watcher.tick() != []  # re-enabled: the pending approval finally notifies


def test_failed_toast_is_retried_not_swallowed_as_seen(tmp_path: Path):
    store = ApprovalStore(tmp_path / "a.db")
    settings = SettingsStore(tmp_path / "a.db")
    attempts: list = []
    watcher = ApprovalWatcher(
        store, settings, notifier=lambda t, b: (attempts.append(1), False)[1]
    )
    _request(store, "one")
    assert watcher.tick() == []
    assert watcher.tick() == []
    assert len(attempts) == 2  # a failed toast does not mark the approval as seen


def test_raising_notifier_does_not_break_the_tick(tmp_path: Path):
    store = ApprovalStore(tmp_path / "a.db")
    settings = SettingsStore(tmp_path / "a.db")

    def boom(_t: str, _b: str) -> bool:
        raise RuntimeError("nope")

    watcher = ApprovalWatcher(store, settings, notifier=boom)
    _request(store, "one")
    assert watcher.tick() == []


def test_routine_failure_watcher_baselines_and_dedupes(tmp_path: Path):
    db = tmp_path / "r.db"
    routines = RoutineStore(db)
    settings = SettingsStore(db)
    routines.add("r1", name="Faturas", kind="invoices", schedule={"type": "every", "minutes": 60})
    old = routines.start_run("r1")
    routines.end_run(old, "r1", status="error")
    calls: list[tuple[str, str]] = []
    watcher = RoutineFailureWatcher(
        routines, settings, notifier=lambda title, body: (calls.append((title, body)), True)[1],
    )
    assert watcher.tick() == []  # existing errors are not retroactively toasted
    assert calls == []
    settings.set("notify_routine_failures", "0")  # the owner can switch alerts off
    disabled = routines.start_run("r1")
    routines.end_run(disabled, "r1", status="error")
    assert watcher.tick() == []
    settings.set("notify_routine_failures", "1")
    assert watcher.tick() == []  # no backlog when switching it on
    new = routines.start_run("r1")
    routines.end_run(new, "r1", status="error")
    assert watcher.tick() == [new]
    assert len(calls) == 1 and "r1" in calls[0][1]
    assert "error" not in calls[0][1].lower()  # no sensitive error detail in toast
    assert watcher.tick() == []
    assert RoutineFailureWatcher(routines, settings, notifier=lambda *_: False).tick() == []


def test_routine_failure_watcher_retry_on_failed_toast(tmp_path: Path):
    db = tmp_path / "r.db"
    routines = RoutineStore(db)
    settings = SettingsStore(db)
    settings.set("notify_routine_failures", "1")
    calls: list[int] = []
    watcher = RoutineFailureWatcher(
        routines, settings, notifier=lambda *_: (calls.append(1), len(calls) > 1)[1],
    )
    assert watcher.tick() == []  # initialize baseline
    routines.add("r1", name="R", kind="invoices", schedule={"type": "every", "minutes": 60})
    run_id = routines.start_run("r1")
    routines.end_run(run_id, "r1", status="error")
    assert watcher.tick() == []
    assert watcher.tick() == [run_id]
    assert len(calls) == 2


def test_routine_failure_toggle_requires_token(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text("tok", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "tok"}).status_code == 200
    url = "/api/setup/notify-routines"
    # On by default now (it was opt-in and never switched on); start from "off" here.
    assert client.get("/api/system/status").json()["routine_failure_notifications_enabled"] is True
    assert client.post(url, json={"enabled": False},
                       headers={"X-EEZE-Token": "tok"}).status_code == 200
    assert client.get("/api/system/status").json()["routine_failure_notifications_enabled"] is False
    routine_db = RoutineStore(tmp_path / "api.db")
    routine_db.add("r1", name="R", kind="invoices", schedule={"type": "every", "minutes": 60})
    old_failure = routine_db.start_run("r1")
    routine_db.end_run(old_failure, "r1", status="error")
    assert client.post(url, json={"enabled": True}).status_code == 401
    response = client.post(url, json={"enabled": True}, headers={"X-EEZE-Token": "tok"})
    assert response.status_code == 200
    assert client.get("/api/system/status").json()["routine_failure_notifications_enabled"] is True
    settings = SettingsStore(tmp_path / "api.db")
    assert old_failure in (settings.get("notified_routine_failures") or "")
    calls = []
    assert RoutineFailureWatcher(routine_db, settings, notifier=lambda *_: calls.append(1)).tick() == []
    assert calls == []
    assert client.post(url, json={"enabled": False}, headers={"X-EEZE-Token": "tok"}).status_code == 200
    while_off = routine_db.start_run("r1")
    routine_db.end_run(while_off, "r1", status="error")
    assert client.post(url, json={"enabled": True}, headers={"X-EEZE-Token": "tok"}).status_code == 200
    assert while_off in (settings.get("notified_routine_failures") or "")
    assert RoutineFailureWatcher(routine_db, settings, notifier=lambda *_: calls.append(1)).tick() == []
    assert calls == []


def test_notify_toggle_endpoint_and_status(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text("tok", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "tok"}).status_code == 200

    assert client.get("/api/system/status").json()["notifications_enabled"] is True
    assert client.post("/api/setup/notify", json={"enabled": False}).status_code == 401
    ok = client.post("/api/setup/notify", json={"enabled": False}, headers={"X-EEZE-Token": "tok"})
    assert ok.status_code == 200 and ok.json()["enabled"] is False
    assert client.get("/api/system/status").json()["notifications_enabled"] is False
    back = client.post("/api/setup/notify", json={"enabled": True}, headers={"X-EEZE-Token": "tok"})
    assert back.json()["enabled"] is True
    assert client.get("/api/system/status").json()["notifications_enabled"] is True


def test_stale_approval_reminder_nudges_once_after_the_threshold(tmp_path: Path):
    import sqlite3

    from eeze_agent.core.notify import StaleApprovalReminder

    store = ApprovalStore(tmp_path / "n.db")
    settings = SettingsStore(tmp_path / "n.db")
    approval_id = store.request(
        runset_id="rs", task="t", task_path="", agent_id="finance", run_index=1,
        step_id="email-summary", step_index=0, action="email_summary",
        risk_class="external_send", reason="r",
    )
    calls: list[str] = []
    reminder = StaleApprovalReminder(store, settings, remind_after_h=4,
                                     notifier=lambda t, b: (calls.append(b), True)[1])
    assert reminder.tick() == []  # fresh: no reminder yet
    with sqlite3.connect(tmp_path / "n.db") as con:
        con.execute("UPDATE approvals SET created_at='2020-01-01T00:00:00+00:00'")
    assert reminder.tick() == [approval_id]
    assert "finance" in calls[0] and "email-summary" in calls[0]
    assert reminder.tick() == []  # only once
    settings.set("notify_approvals", "0")
    assert StaleApprovalReminder(store, settings, notifier=lambda *_: True).tick() == []
