"""Tiny key/value settings on ``~/.eeze/eeze.db`` (F5: wizard state, flags)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from eeze_agent.core.approvals import ApprovalStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class SettingsStore:
    def __init__(self, db_path: Path | None = None) -> None:
        store = ApprovalStore(db_path)  # ensures the db exists
        self.path = store.path
        with self._connect() as con:
            con.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def get(self, key: str) -> str | None:
        with self._connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def get_bool(self, key: str) -> bool:
        return (self.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}

    def set(self, key: str, value: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def delete(self, key: str) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM settings WHERE key=?", (key,))
