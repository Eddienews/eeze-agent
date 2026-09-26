"""Spend ledger + daily budget per agent (stdlib only).

Every paid model call is recorded here (model, tokens, estimated USD). Before any step that
would call a paid brain, the loop asks :func:`check_budget`; once an agent's spend for the
local day reaches its cap, the run stops with ``budget_exceeded`` instead of spending more.

The cap comes from, in order: the agent's ``budget_usd_daily`` (agents.yaml / UI), the
``EEZE_BUDGET_USD_DAILY`` env var, then :data:`DEFAULT_BUDGET_USD_DAILY`. ``0`` means "no cap".
Estimates use :mod:`eeze_agent.core.pricing` — conservative for unknown models, $0 for the
flat Codex plan — so they are a guard rail, not a bill.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from eeze_agent.core.approvals import default_db_path
from eeze_agent.core.pricing import estimate_cost_usd

DEFAULT_BUDGET_USD_DAILY = 2.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS spend (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  day TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  model TEXT,
  tokens INTEGER NOT NULL DEFAULT 0,
  usd REAL NOT NULL DEFAULT 0,
  source TEXT
);
CREATE INDEX IF NOT EXISTS idx_spend_day ON spend(day, agent_id);
"""


class BudgetExceeded(RuntimeError):
    def __init__(self, agent_id: str, spent: float, budget: float) -> None:
        self.agent_id, self.spent, self.budget = agent_id, spent, budget
        super().__init__(
            f"daily budget reached for agent {agent_id!r}: ${spent:.4f} of ${budget:.2f} "
            "(raise it in the agent settings or EEZE_BUDGET_USD_DAILY)"
        )


def _today() -> str:
    return datetime.now().date().isoformat()  # noqa: DTZ005 — budgets follow the local day


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def record(agent_id: str | None, model: str | None, tokens: int | None, *,
           source: str = "", db_path: Path | None = None) -> float:
    """Record one call; returns its estimated USD. Zero-token calls are not stored."""
    tokens = max(0, int(tokens or 0))
    if not tokens:
        return 0.0
    usd = estimate_cost_usd(model, tokens)
    with _connect(db_path) as con:
        con.execute(
            "INSERT INTO spend (id, ts, day, agent_id, model, tokens, usd, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("sp-" + uuid.uuid4().hex[:12], datetime.now(UTC).isoformat(timespec="seconds"),
             _today(), agent_id or "default", model or "", tokens, usd, source),
        )
    return usd


def spent_today(agent_id: str | None = None, *, db_path: Path | None = None) -> float:
    query, args = "SELECT COALESCE(SUM(usd), 0) AS s FROM spend WHERE day=?", [_today()]
    if agent_id:
        query += " AND agent_id=?"
        args.append(agent_id)
    with _connect(db_path) as con:
        return float(con.execute(query, args).fetchone()["s"] or 0.0)


def today_by_agent(*, db_path: Path | None = None) -> dict[str, dict]:
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT agent_id, COALESCE(SUM(usd),0) AS usd, COALESCE(SUM(tokens),0) AS tokens, "
            "COUNT(*) AS calls FROM spend WHERE day=? GROUP BY agent_id", (_today(),)
        ).fetchall()
    return {r["agent_id"]: {"usd": round(float(r["usd"]), 6), "tokens": int(r["tokens"]),
                            "calls": int(r["calls"])} for r in rows}


def budget_for(agent: object | None) -> float | None:
    """Effective daily cap in USD, or ``None`` for no cap."""
    value = getattr(agent, "budget_usd_daily", None)
    if value is None:
        raw = (os.environ.get("EEZE_BUDGET_USD_DAILY") or "").strip()
        try:
            value = float(raw) if raw else DEFAULT_BUDGET_USD_DAILY
        except ValueError:
            value = DEFAULT_BUDGET_USD_DAILY
    value = float(value)
    return value if value > 0 else None


def check_budget(agent: object, *, db_path: Path | None = None) -> None:
    """Raise :class:`BudgetExceeded` once today's spend reached the agent's cap."""
    budget = budget_for(agent)
    if budget is None:
        return
    agent_id = str(getattr(agent, "id", "") or "default")
    try:
        spent = spent_today(agent_id, db_path=db_path)
    except sqlite3.Error:
        return  # a locked/broken ledger must not stop work; the next check tries again
    if spent >= budget:
        raise BudgetExceeded(agent_id, spent, budget)
