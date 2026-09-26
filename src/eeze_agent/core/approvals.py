"""Approval queue, grants and paused-run state (F2 / M1). SQLite, stdlib only.

The DB lives at ``~/.eeze/eeze.db`` (override with the ``EEZE_DB`` env var or the
``db_path`` argument). Tables:

- ``approvals``  — one row per gate pause (pending → approved | denied)
- ``grants``     — scoped, revocable, TTL-capped permissions ("always allow this")
- ``run_states`` — everything needed to resume a paused run-set from the exact step
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  runset_id TEXT,
  task TEXT,
  task_path TEXT,
  agent_id TEXT,
  run_index INTEGER,
  step_id TEXT,
  step_index INTEGER,
  action TEXT,
  risk_class TEXT,
  reason TEXT,
  payload TEXT,
  action_digest TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  decision TEXT,
  decided_by TEXT,
  decided_at TEXT,
  grant_id TEXT
);
CREATE TABLE IF NOT EXISTS grants (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  risk_class TEXT NOT NULL,
  scope TEXT NOT NULL,
  task TEXT,
  expires_at TEXT,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS run_states (
  id TEXT PRIMARY KEY,
  approval_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'waiting',
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_grants_lookup ON grants(agent_id, risk_class);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


DEFAULT_PENDING_TTL_HOURS = 72.0


def pending_ttl_hours() -> float:
    """How long a pending approval may wait before it expires (``EEZE_APPROVAL_TTL_HOURS``).

    ``0`` disables expiry. Default 72 h: long enough for a weekend, short enough that a
    forgotten gate does not freeze a daily routine indefinitely.
    """
    raw = os.environ.get("EEZE_APPROVAL_TTL_HOURS", "").strip()
    try:
        return max(0.0, float(raw)) if raw else DEFAULT_PENDING_TTL_HOURS
    except ValueError:
        return DEFAULT_PENDING_TTL_HOURS


def default_db_path() -> Path:
    env = os.environ.get("EEZE_DB")
    if env:
        return Path(env)
    return Path.home() / ".eeze" / "eeze.db"


def approval_digest(*, task: object, task_path: Path | None, agent: object,
                    runset_id: str, run_index: int, step_index: int,
                    risk_class: str, vars: dict) -> str:
    """Canonical identity of the full task and resolved runtime context at a gate."""
    data = {
        "version": 1,
        "task": task.model_dump(),
        "task_path": str(task_path) if task_path else "",
        "agent": agent.model_dump(),
        "runset_id": runset_id,
        "run_index": run_index,
        "step_index": step_index,
        "risk_class": risk_class,
        "vars": vars,
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ApprovalStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.path = Path(db_path) if db_path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)
            # Existing installations predate action binding. Their NULL digests fail closed.
            columns = {row["name"] for row in con.execute("PRAGMA table_info(approvals)")}
            if "action_digest" not in columns:
                con.execute("ALTER TABLE approvals ADD COLUMN action_digest TEXT")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con

    # ---------------- approvals ----------------

    def request(
        self,
        *,
        runset_id: str,
        task: str,
        task_path: str,
        agent_id: str,
        run_index: int,
        step_id: str,
        step_index: int,
        action: str,
        risk_class: str,
        reason: str,
        payload: dict | None = None,
        action_digest: str | None = None,
        run_state=None,
    ) -> str:
        """Open a pending approval.

        ``run_state`` (optional) is ``callable(approval_id) -> dict``: the paused-run state
        is then written in the *same* transaction, so a crash can never leave a pending
        approval with nothing to resume (such rows used to freeze their routine).
        """
        approval_id = "ap-" + uuid.uuid4().hex[:10]
        with self._connect() as con:
            con.execute(
                "INSERT INTO approvals (id, created_at, runset_id, task, task_path, "
                "agent_id, run_index, step_id, step_index, action, risk_class, reason, payload, action_digest) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    approval_id, _now(), runset_id, task, task_path, agent_id,
                    int(run_index), step_id, int(step_index), action, risk_class, reason,
                    json.dumps(payload or {}), action_digest,
                ),
            )
            if run_state is not None:
                con.execute(
                    "INSERT INTO run_states (id, approval_id, created_at, payload) VALUES (?,?,?,?)",
                    ("rs-" + uuid.uuid4().hex[:10], approval_id, _now(),
                     json.dumps(run_state(approval_id), default=str)),
                )
        return approval_id

    def get(self, approval_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        return dict(row) if row else None

    def list(self, status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        query = "SELECT * FROM approvals"
        args: list = []
        if status:
            query += " WHERE status=?"
            args.append(status)
        query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        args.extend([int(limit), int(offset)])
        with self._connect() as con:
            rows = con.execute(query, args).fetchall()
        return [dict(r) for r in rows]

    def count(self, status: str | None = None) -> int:
        query = "SELECT COUNT(*) AS n FROM approvals"
        args: list = []
        if status:
            query += " WHERE status=?"
            args.append(status)
        with self._connect() as con:
            row = con.execute(query, args).fetchone()
        return int(row["n"]) if row else 0

    def decide(
        self, approval_id: str, decision: str, decided_by: str = "local", reason: str | None = None
    ) -> dict:
        if decision not in {"approve", "deny"}:
            raise ValueError(f"decision must be approve|deny, got {decision!r}")
        status = "approved" if decision == "approve" else "denied"
        with self._connect() as con:
            cur = con.execute(
                "UPDATE approvals SET status=?, decision=?, decided_by=?, decided_at=?, "
                "reason=COALESCE(?, reason) WHERE id=? AND status='pending'",
                (status, decision, decided_by, _now(), reason, approval_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"no pending approval {approval_id!r}")
            if decision == "deny":
                con.execute(
                    "UPDATE run_states SET status='denied' WHERE approval_id=?", (approval_id,)
                )
                try:  # a denied gate ends the routine run parked on it
                    stamp = datetime.now().replace(microsecond=0).isoformat()  # noqa: DTZ005
                    con.execute(
                        "UPDATE routine_runs SET status='denied', ended_at=COALESCE(ended_at, ?) "
                        "WHERE approval_id=? AND status='needs_approval'",
                        (stamp, approval_id),
                    )
                except sqlite3.OperationalError:
                    pass
        row = self.get(approval_id)
        assert row is not None
        return row

    def _close_pending(self, con: sqlite3.Connection, approval_id: str, status: str,
                       decided_by: str, reason: str | None) -> bool:
        """Close one pending approval as ``abandoned``/``expired`` and release what it blocks.

        Unlike :meth:`decide`, this works on approvals that can no longer resume (legacy
        rows with no digest or run state): nothing is resumed, the paused run-state is
        retired and any routine run parked on it is closed, so the scheduler stops
        treating the routine as "still open".
        """
        cur = con.execute(
            "UPDATE approvals SET status=?, decision=?, decided_by=?, decided_at=?, "
            "reason=COALESCE(?, reason) WHERE id=? AND status='pending'",
            (status, status, decided_by, _now(), reason, approval_id),
        )
        if cur.rowcount == 0:
            return False
        con.execute(
            "UPDATE run_states SET status=? WHERE approval_id=? AND status='waiting'",
            (status, approval_id),
        )
        try:
            # Local wall-clock, matching the routines store.
            stamp = datetime.now().replace(microsecond=0).isoformat()  # noqa: DTZ005
            con.execute(
                "UPDATE routine_runs SET status=?, ended_at=COALESCE(ended_at, ?) "
                "WHERE approval_id=? AND status='needs_approval'",
                (status, stamp, approval_id),
            )
        except sqlite3.OperationalError:
            pass  # routines table not created yet (no routine ever ran on this db)
        return True

    def abandon(self, approval_id: str, decided_by: str = "local", reason: str | None = None) -> dict:
        """Give up on a pending approval without running anything (works on legacy rows)."""
        with self._connect() as con:
            if not self._close_pending(con, approval_id, "abandoned", decided_by, reason):
                raise KeyError(f"no pending approval {approval_id!r}")
        row = self.get(approval_id)
        assert row is not None
        return row

    def expire_stale(self, max_age_hours: float, now: datetime | None = None) -> list[str]:
        """Expire pending approvals older than ``max_age_hours``; returns their ids.

        An approval nobody decides must not freeze its routine forever: once expired the
        next scheduled run starts fresh and asks again.
        """
        if max_age_hours <= 0:
            return []
        cutoff = ((now or datetime.now(UTC)) - timedelta(hours=max_age_hours)).isoformat(
            timespec="seconds")
        with self._connect() as con:
            rows = con.execute(
                "SELECT id FROM approvals WHERE status='pending' AND created_at<?", (cutoff,)
            ).fetchall()
            expired = [r["id"] for r in rows
                       if self._close_pending(con, r["id"], "expired", "system",
                                              f"no decision within {max_age_hours:g}h")]
        return expired

    def link_grant(self, approval_id: str, grant_id: str) -> None:
        with self._connect() as con:
            con.execute("UPDATE approvals SET grant_id=? WHERE id=?", (grant_id, approval_id))

    # ---------------- grants ----------------

    def grant(
        self,
        *,
        agent_id: str,
        risk_class: str,
        scope: str,
        task: str | None = None,
        ttl_hours: int | None = None,
    ) -> str:
        if scope not in {"task", "agent"}:
            raise ValueError(f"grant scope must be task|agent, got {scope!r}")
        grant_id = "gr-" + uuid.uuid4().hex[:10]
        expires_at = None
        if ttl_hours:
            expires_at = (datetime.now(UTC) + timedelta(hours=int(ttl_hours))).isoformat(
                timespec="seconds"
            )
        with self._connect() as con:
            con.execute(
                "INSERT INTO grants (id, created_at, agent_id, risk_class, scope, task, expires_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (grant_id, _now(), agent_id, risk_class, scope, task if scope == "task" else None, expires_at),
            )
        return grant_id

    def active_grant(
        self, agent_id: str, risk_class: str, task: str, now: datetime | None = None
    ) -> dict | None:
        """First grant covering (agent, class, task) that is neither revoked nor expired."""
        now_iso = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM grants WHERE agent_id=? AND risk_class=? AND revoked_at IS NULL",
                (agent_id, risk_class),
            ).fetchall()
        for row in rows:
            if row["expires_at"] and row["expires_at"] <= now_iso:
                continue
            if row["scope"] == "agent":
                return dict(row)
            if row["scope"] == "task" and (row["task"] or "") == task:
                return dict(row)
        return None

    def list_grants(self, include_revoked: bool = False) -> list[dict]:
        query = "SELECT * FROM grants"
        if not include_revoked:
            query += " WHERE revoked_at IS NULL"
        query += " ORDER BY created_at DESC, id DESC"
        with self._connect() as con:
            rows = con.execute(query).fetchall()
        return [dict(r) for r in rows]

    def revoke_grant(self, grant_id: str) -> bool:
        with self._connect() as con:
            cur = con.execute(
                "UPDATE grants SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (_now(), grant_id),
            )
        return cur.rowcount > 0

    # ---------------- paused-run state ----------------

    def save_run_state(self, approval_id: str, payload: dict) -> str:
        state_id = "rs-" + uuid.uuid4().hex[:10]
        with self._connect() as con:
            con.execute(
                "UPDATE run_states SET status='superseded' "
                "WHERE approval_id=? AND status='waiting'",
                (approval_id,),
            )
            con.execute(
                "INSERT INTO run_states (id, approval_id, created_at, payload) VALUES (?,?,?,?)",
                (state_id, approval_id, _now(), json.dumps(payload, default=str)),
            )
        return state_id

    def run_state_for(self, approval_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM run_states WHERE approval_id=? ORDER BY rowid DESC LIMIT 1",
                (approval_id,),
            ).fetchone()
        return dict(row) if row else None

    def claim_resume(self, approval_id: str, payload: dict, digest: str) -> str:
        """Consume a matching one-run approval once, before any driver action."""
        with self._connect() as con:
            approval = con.execute(
                "SELECT status, action_digest FROM approvals WHERE id=?", (approval_id,)
            ).fetchone()
            state = con.execute(
                "SELECT id, status, payload FROM run_states WHERE approval_id=? "
                "ORDER BY rowid DESC LIMIT 1", (approval_id,)
            ).fetchone()
            already_resumed = con.execute(
                "SELECT 1 FROM run_states WHERE approval_id=? AND status='resumed' LIMIT 1",
                (approval_id,),
            ).fetchone()
            if (not approval or approval["status"] != "approved" or not approval["action_digest"]
                    or approval["action_digest"] != digest or not state or already_resumed
                    or state["status"] != "waiting" or json.loads(state["payload"]) != payload):
                raise ValueError("approval identity mismatch or already consumed; request a new approval")
            cur = con.execute(
                "UPDATE run_states SET status='resumed' WHERE id=? AND status='waiting'",
                (state["id"],),
            )
            if cur.rowcount != 1:
                raise ValueError("approval already consumed; request a new approval")
            return state["id"]

    def set_run_state_status(self, state_id: str, status: str) -> None:
        with self._connect() as con:
            con.execute("UPDATE run_states SET status=? WHERE id=?", (status, state_id))

    def close(self) -> None:  # symmetry with other stores; connections are per-call
        return None
