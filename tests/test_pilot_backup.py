"""F6 — pilot readiness checks + local backup."""

from __future__ import annotations

import zipfile
from pathlib import Path

from eeze_agent.core.backup import create_backup
from eeze_agent.core.pilot import pilot_checks
from eeze_agent.core.routines import RoutineStore


def _env(**values: str) -> dict[str, str]:
    return dict(values)


def _ok_probe(host: str, user: str, password: str):
    return {"host": host, "folder": "INBOX", "messages": 7}


def test_pilot_checks_all_green(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    store = RoutineStore()
    store.add("invoices", name="Faturas", kind="invoices", schedule={"type": "daily", "at": "08:00"})
    startup = tmp_path / "Startup"
    startup.mkdir()
    (startup / "Eeze Agent service.cmd").write_text("@echo off\n", encoding="utf-8")
    env = _env(
        EEZE_IMAP_USER="u@example.com",
        EEZE_IMAP_APP_PASSWORD="pw",
        EEZE_EXTRACT_API_KEY="k",
        EEZE_PLANNER_API_KEY="k",
    )
    result = pilot_checks(
        repo_root=tmp_path,
        home=tmp_path,
        startup_dir=startup,
        env=env,
        daemon_status_fn=lambda: {"running": True, "responding": True, "pid": 1},
        imap_probe_fn=_ok_probe,
        routine_store=store,
    )
    assert result["ok"] is True
    names = [c["name"] for c in result["checks"]]
    assert "Daemon" in names and "Mailbox" in names and "Routine 'invoices'" in names


def test_pilot_checks_flag_missing_pieces(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    store = RoutineStore()
    result = pilot_checks(
        repo_root=tmp_path,
        home=tmp_path,
        startup_dir=tmp_path / "nope",
        env=_env(),  # nothing configured
        daemon_status_fn=lambda: {"running": False, "responding": False},
        routine_store=store,
    )
    assert result["ok"] is False
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["Daemon"]["ok"] is False
    assert by_name["Routine 'invoices'"]["ok"] is False
    assert by_name["Mailbox"]["ok"] is False
    assert by_name["Autostart"]["ok"] is False and by_name["Autostart"]["critical"] is False


def test_pilot_probe_failure_is_readable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    store = RoutineStore()
    store.add("invoices", name="F", kind="invoices", schedule={"type": "daily", "at": "08:00"})

    def boom(host, user, password):
        raise RuntimeError("AUTHENTICATIONFAILED")

    result = pilot_checks(
        repo_root=tmp_path,
        home=tmp_path,
        startup_dir=tmp_path,
        env=_env(EEZE_IMAP_USER="u@e.com", EEZE_IMAP_APP_PASSWORD="pw", EEZE_EXTRACT_API_KEY="k"),
        daemon_status_fn=lambda: {"running": True, "responding": True},
        imap_probe_fn=boom,
        routine_store=store,
    )
    mailbox = {c["name"]: c for c in result["checks"]}["Mailbox"]
    assert mailbox["ok"] is False and "AUTHENTICATIONFAILED" in mailbox["detail"]


def test_backup_state_and_env(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "eeze.db").write_bytes(b"SQLite format 3\x00 fake")
    (home / "resume-ap-1.log").write_text("log", encoding="utf-8")
    routines_dir = home / "routines"
    routines_dir.mkdir()
    (routines_dir / "run-invoices.log").write_text("routine log", encoding="utf-8")
    (tmp_path / ".env").write_text("EEZE_IMAP_USER=u\n", encoding="utf-8")

    result = create_backup(repo_root=tmp_path, home=home, out_dir=tmp_path / "out")
    archive = Path(result["archive"])
    assert archive.exists() and result["bytes"] > 0 and len(result["sha256"]) == 64
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert "eeze/eeze.db" in names
    assert "eeze/routines/run-invoices.log" in names
    assert "env/.env" in names
    assert result["counts"] == {"state": 1, "logs": 2, "env": 1}


def test_backup_with_runs(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "eeze.db").write_bytes(b"db")
    runset = tmp_path / "artifacts" / "runs" / "rs1"
    runset.mkdir(parents=True)
    (runset / "journal.jsonl").write_text("{}\n", encoding="utf-8")
    audit = tmp_path / "artifacts" / "audits" / "export-rs1"
    audit.mkdir(parents=True)
    (audit / "REPORT.md").write_text("report", encoding="utf-8")

    result = create_backup(repo_root=tmp_path, home=home, out_dir=tmp_path / "out", with_runs=True)
    with zipfile.ZipFile(result["archive"]) as zf:
        names = set(zf.namelist())
    assert "artifacts/runs/rs1/journal.jsonl" in names
    assert "artifacts/audits/export-rs1/REPORT.md" in names
    assert result["counts"]["artifacts"] == 2
