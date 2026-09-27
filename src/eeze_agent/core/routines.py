"""Routines + scheduler (F4 / M1): named, scheduled runs with the F2 gate.

A routine is a named spec (kind + schedule + params) stored in ``~/.eeze/eeze.db``.
The scheduler lives in the API daemon: every tick it spawns due routines as detached
``eeze routines run <id>`` processes. Kinds:

- ``invoices`` — pull the mailbox (read-only) → verified ledger + anomalies; optional
  ``email_summary`` step that is gated as ``external_send`` (approve → it sends).
- ``task``     — run a task YAML through the gated loop (pauses for approval like any
  gated run; resumes with ``eeze run --resume``).

Schedules are deliberately simple: ``{"type": "daily", "at": "08:00"}`` or
``{"type": "every", "minutes": N}``. Local wall-clock time, like the invoices vertical.
``{"type": "watch"}`` (Files missions only) has no clock: the scheduler starts it when the
mission's folder changes and the plan would change something (see ``core/watch.py``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from eeze_agent.core import procs
from eeze_agent.core.approvals import ApprovalStore, pending_ttl_hours

log = logging.getLogger("eeze.routines")

# A ``running`` row with no live worker is an orphan (reboot, power loss, killed worker).
# Rows from before PIDs were recorded are only reaped once they are this old.
STALE_RUNNING_HOURS = 12.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  schedule TEXT NOT NULL,
  params TEXT NOT NULL DEFAULT '{}',
  agent_id TEXT NOT NULL DEFAULT 'default',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_run_at TEXT,
  last_status TEXT,
  next_run_at TEXT
);
CREATE TABLE IF NOT EXISTS routine_runs (
  id TEXT PRIMARY KEY,
  routine_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT,
  detail TEXT,
  approval_id TEXT,
  log_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_routine_runs ON routine_runs(routine_id, started_at);
"""


def path_safe(routine_id: str) -> str:
    """Routine ids in file/folder names: ``mission:m1`` would be an NTFS alternate data
    stream (``run-mission`` + stream ``m1.log``) on Windows, not a file."""
    return re.sub(r"[^A-Za-z0-9_.-]", "-", str(routine_id))


def routine_log_path(home: Path, routine_id: str) -> Path:
    return home / "routines" / f"run-{path_safe(routine_id)}.log"


def _now_local() -> datetime:
    # Routines follow the local wall clock by design (business hours, like invoices).
    return datetime.now()  # noqa: DTZ005


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def compute_next_run(schedule: dict, base: datetime | None = None) -> str | None:
    """Next due timestamp (local, ISO) for the simple schedule shapes (None: folder watch)."""
    base = base or _now_local()
    kind = str(schedule.get("type") or "").lower()
    if kind == "watch":
        return None
    if kind == "every":
        minutes = max(1, int(schedule.get("minutes") or 60))
        return _iso(base + timedelta(minutes=minutes))
    if kind == "daily":
        at = str(schedule.get("at") or "08:00")
        try:
            hour, minute = (int(x) for x in at.split(":", 1))
        except ValueError as exc:
            raise ValueError(f"daily schedule needs at like '08:00', got {at!r}") from exc
        candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= base:
            candidate += timedelta(days=1)
        return _iso(candidate)
    raise ValueError(f"unknown schedule type: {kind!r} (daily|every|watch)")


def task_routine_status(summary: dict) -> str:
    """Map a task runset to the routine's honest outcome (not the journal lifecycle)."""
    if summary.get("status") == "needs_approval":
        return "needs_approval"
    if summary.get("status") != "done":
        return "error"
    try:
        rate = summary.get("success_rate_all_runs") or summary["success_rate"]
        successes, total = (int(n) for n in rate.split("/"))
        if (total < 1 or successes != total
                or (summary.get("task_runs") is not None
                    and summary.get("runs_completed") != summary["task_runs"])):
            return "error"
    except (KeyError, TypeError, ValueError):
        return "error"
    return "ok"


class RoutineStore:
    def __init__(self, db_path: Path | None = None) -> None:
        store = ApprovalStore(db_path)  # ensures the db exists + base tables
        self.path = store.path
        with self._connect() as con:
            con.executescript(SCHEMA)
            columns = {row["name"] for row in con.execute("PRAGMA table_info(routine_runs)")}
            if "pid" not in columns:
                con.execute("ALTER TABLE routine_runs ADD COLUMN pid INTEGER")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con

    # ---------------- routines CRUD ----------------

    def add(
        self,
        routine_id: str,
        *,
        name: str,
        kind: str,
        schedule: dict,
        params: dict | None = None,
        agent_id: str = "default",
        enabled: bool = True,
    ) -> dict:
        with self._connect() as con:
            cur = con.execute("SELECT id FROM routines WHERE id=?", (routine_id,))
            exists = cur.fetchone() is not None
        next_run = compute_next_run(schedule)
        with self._connect() as con:
            if exists:
                con.execute(
                    "UPDATE routines SET name=?, kind=?, schedule=?, params=?, agent_id=?, "
                    "enabled=?, next_run_at=? WHERE id=?",
                    (name, kind, json.dumps(schedule), json.dumps(params or {}), agent_id,
                     1 if enabled else 0, next_run, routine_id),
                )
            else:
                con.execute(
                    "INSERT INTO routines (id, name, kind, schedule, params, agent_id, "
                    "enabled, created_at, next_run_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (routine_id, name, kind, json.dumps(schedule), json.dumps(params or {}),
                     agent_id, 1 if enabled else 0, _iso(_now_local()), next_run),
                )
        row = self.get(routine_id)
        assert row is not None
        return row

    def get(self, routine_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM routines WHERE id=?", (routine_id,)).fetchone()
        return self._row(row) if row else None

    def list(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM routines ORDER BY id").fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["schedule"] = json.loads(data.get("schedule") or "{}")
        data["params"] = json.loads(data.get("params") or "{}")
        data["enabled"] = bool(data.get("enabled"))
        return data

    def set_enabled(self, routine_id: str, enabled: bool) -> bool:
        with self._connect() as con:
            cur = con.execute(
                "UPDATE routines SET enabled=?, next_run_at=? WHERE id=?",
                (
                    1 if enabled else 0,
                    compute_next_run(self.get(routine_id)["schedule"]) if enabled else None,
                    routine_id,
                ),
            )
        return cur.rowcount > 0

    def remove(self, routine_id: str) -> bool:
        with self._connect() as con:
            cur = con.execute("DELETE FROM routines WHERE id=?", (routine_id,))
        return cur.rowcount > 0

    # ---------------- due / spawn bookkeeping ----------------

    def due(self, now: datetime | None = None) -> list[dict]:
        now_iso = _iso(now or _now_local())
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM routines WHERE enabled=1 AND next_run_at IS NOT NULL "
                "AND next_run_at<=? ORDER BY next_run_at",
                (now_iso,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def has_open_run(self, routine_id: str) -> bool:
        """True while a run is in flight or still waiting at the gate (approval pending).

        Prevents the scheduler from stacking a second run of the same routine on top of
        one that is still executing or parked in the approvals queue.
        """
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM routine_runs rr WHERE rr.routine_id=? AND ("
                "rr.status='running' OR (rr.status='needs_approval' AND rr.approval_id IN "
                "(SELECT id FROM approvals WHERE status='pending'))) LIMIT 1",
                (routine_id,),
            ).fetchone()
        return row is not None

    def postpone(self, routine_id: str, *, now: datetime | None = None) -> None:
        row = self.get(routine_id)
        if row is None:
            return
        with self._connect() as con:
            con.execute(
                "UPDATE routines SET next_run_at=? WHERE id=?",
                (compute_next_run(row["schedule"], now), routine_id),
            )

    def mark_spawned(self, routine_id: str, *, now: datetime | None = None) -> None:
        row = self.get(routine_id)
        if row is None:
            return
        with self._connect() as con:
            con.execute(
                "UPDATE routines SET last_run_at=?, last_status='spawned', next_run_at=? WHERE id=?",
                (_iso(now or _now_local()), compute_next_run(row["schedule"], now), routine_id),
            )

    def record_spawn_failure(
        self, routine_id: str, *, now: datetime | None = None, log_path: str = "",
        error_type: str, errno: int | None,
    ) -> None:
        """Record a failed launch and advance its schedule in one DB transaction."""
        row = self.get(routine_id)
        if row is None:
            return
        stamp = _iso(_now_local())
        detail = {"spawn_failure": {"type": error_type, "errno": errno}}
        with self._connect() as con:
            con.execute(
                "INSERT INTO routine_runs (id, routine_id, started_at, ended_at, status, detail, log_path) "
                "VALUES (?,?,?,?,?,?,?)",
                ("rr-" + uuid.uuid4().hex[:10], routine_id, stamp, stamp, "error",
                 json.dumps(detail), log_path),
            )
            con.execute(
                "UPDATE routines SET last_status='error', next_run_at=? WHERE id=?",
                (compute_next_run(row["schedule"], now), routine_id),
            )

    # ---------------- run records ----------------

    def start_run(self, routine_id: str, *, log_path: str = "", pid: int | None = None) -> str:
        """Open a ``running`` record owned by ``pid`` (default: this process)."""
        run_id = "rr-" + uuid.uuid4().hex[:10]
        with self._connect() as con:
            con.execute(
                "INSERT INTO routine_runs (id, routine_id, started_at, status, log_path, pid) "
                "VALUES (?,?,?,?,?,?)",
                (run_id, routine_id, _iso(_now_local()), "running", log_path,
                 int(pid) if pid else os.getpid()),
            )
        return run_id

    def reap_orphans(
        self, *, now: datetime | None = None, alive=procs.pid_alive,
        stale_hours: float = STALE_RUNNING_HOURS,
    ) -> list[str]:
        """Close ``running`` rows whose worker is gone; returns the reaped run ids.

        Without this a reboot or a killed worker leaves the row ``running`` forever and
        :meth:`has_open_run` postpones the routine on every tick — silently, for good.
        """
        now = now or _now_local()
        cutoff = _iso(now - timedelta(hours=stale_hours))
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, routine_id, started_at, pid FROM routine_runs WHERE status='running'"
            ).fetchall()
        reaped: list[str] = []
        for row in rows:
            pid = row["pid"]
            if pid:
                if alive(int(pid)):
                    continue
                reason = "worker process is gone (reboot, crash or killed)"
            elif row["started_at"] < cutoff:
                reason = f"no worker record and running for more than {stale_hours:g}h"
            else:
                continue
            with self._connect() as con:
                cur = con.execute(
                    "UPDATE routine_runs SET status='error', ended_at=?, detail=? "
                    "WHERE id=? AND status='running'",
                    (_iso(now), json.dumps({"orphaned": True, "error": reason}), row["id"]),
                )
                if cur.rowcount:
                    con.execute("UPDATE routines SET last_status='error' WHERE id=?",
                                (row["routine_id"],))
                    reaped.append(row["id"])
        return reaped

    def end_run(
        self,
        run_id: str,
        routine_id: str,
        *,
        status: str,
        detail: dict | None = None,
        approval_id: str | None = None,
    ) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE routine_runs SET ended_at=?, status=?, detail=?, approval_id=? WHERE id=?",
                (_iso(_now_local()), status, json.dumps(detail or {}), approval_id, run_id),
            )
            con.execute(
                "UPDATE routines SET last_status=? WHERE id=?", (status, routine_id)
            )

    def runs(self, routine_id: str | None = None, limit: int = 50) -> list[dict]:
        query = "SELECT * FROM routine_runs"
        args: list = []
        if routine_id:
            query += " WHERE routine_id=?"
            args.append(routine_id)
        query += " ORDER BY started_at DESC, id DESC LIMIT ?"
        args.append(int(limit))
        with self._connect() as con:
            rows = con.execute(query, args).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["detail"] = json.loads(data.get("detail") or "{}")
            out.append(data)
        return out


# ---------------- scheduler ----------------

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def spawn_detached(argv: list[str], *, cwd: Path, log_path: Path) -> int:
    """Launch ``python -m eeze_agent.cli <argv…>`` detached; returns the pid."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import sys\n"
        "from eeze_agent.cli import main\n"
        f"sys.exit(main({argv!r}))\n"
    )
    logfh = log_path.open("ab")
    kwargs: dict = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": logfh,
        "stderr": logfh,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen([sys.executable, "-c", code], **kwargs)
        return proc.pid
    finally:
        logfh.close()


class Scheduler:
    """Ticks the routine store and spawns due routines (thread lives in the daemon)."""

    def __init__(
        self,
        store: RoutineStore,
        *,
        repo_root: Path,
        home: Path,
        interval_s: float = 30.0,
        spawn=spawn_detached,
    ) -> None:
        self.store = store
        self.repo_root = repo_root
        self.home = home
        self.interval_s = interval_s
        self.spawn = spawn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick_at: str | None = None
        self.last_housekeeping: dict = {}

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def housekeeping(self, now: datetime | None = None) -> dict:
        """Release what would otherwise block routines forever (runs every tick)."""
        reaped = self.store.reap_orphans(now=now)
        expired = ApprovalStore(self.store.path).expire_stale(pending_ttl_hours())
        for run_id in reaped:
            log.warning("routine run %s reaped as orphaned", run_id)
        for approval_id in expired:
            log.warning("approval %s expired without a decision", approval_id)
        return {"reaped": reaped, "expired": expired}

    def tick(self, now: datetime | None = None) -> list[str]:
        spawned: list[str] = []
        self.last_housekeeping = self.housekeeping(now)
        for routine in self.store.due(now):
            log = routine_log_path(self.home, routine["id"])
            if self.store.has_open_run(routine["id"]):
                # Its previous run is still executing or waiting for a decision — don't stack,
                # but say so: a silent skip looked exactly like a dead scheduler.
                self.store.postpone(routine["id"], now=now)
                log_line(log, "skipped: previous run still running or waiting for approval")
                continue
            try:
                self.spawn(["routines", "run", routine["id"]], cwd=self.repo_root, log_path=log)
            except OSError as exc:
                self.store.record_spawn_failure(
                    routine["id"], now=now, log_path=str(log),
                    error_type=type(exc).__name__, errno=exc.errno,
                )
                log_line(log, f"spawn failed: {type(exc).__name__} (errno={exc.errno})")
                continue
            self.store.mark_spawned(routine["id"], now=now)
            spawned.append(routine["id"])
        spawned += self.watch_tick(now)
        return spawned

    def watch_tick(self, now: datetime | None = None) -> list[str]:
        """Folder-watch missions: start one when its folder changed and the plan has work."""
        from eeze_agent.core import watch

        spawned: list[str] = []
        clock = now.timestamp() if now is not None else None
        for routine in self.store.list():
            if not routine["enabled"] or (routine.get("schedule") or {}).get("type") != "watch":
                continue
            rid = routine["id"]
            result = watch.evaluate(self.home, rid, busy=self.store.has_open_run(rid), now=clock)
            if result["action"] != "run":
                continue
            log = routine_log_path(self.home, rid)
            try:
                self.spawn(["routines", "run", rid], cwd=self.repo_root, log_path=log)
            except OSError as exc:
                self.store.record_spawn_failure(
                    rid, now=now, log_path=str(log),
                    error_type=type(exc).__name__, errno=exc.errno,
                )
                log_line(log, f"watch: spawn failed: {type(exc).__name__} (errno={exc.errno})")
                continue
            watch.mark_triggered(self.home, rid, now=clock)
            self.store.mark_spawned(rid, now=now)
            log_line(log, f"watch: the folder changed — {result['detail']}; waiting for your approval")
            spawned.append(rid)
        return spawned

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.tick()
                    self.last_tick_at = _iso(_now_local())
                except Exception as exc:  # noqa: BLE001 — one failed tick must not kill the daemon
                    # The daemon captures stderr in api.log; avoid raw error text (may be sensitive).
                    log.error(
                        "scheduler tick failed: %s (errno=%s)",
                        type(exc).__name__, getattr(exc, "errno", None),
                    )
                self._stop.wait(self.interval_s)

        self._thread = threading.Thread(target=loop, name="eeze-routines", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def log_line(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")
