"""Run journal: append-only JSONL event log + per-run artifact directory."""

from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class RunJournal:
    """Artifacts + event log for one run-set (e.g. 20 runs of a task).

    Layout::

        artifacts/runs/<runset_id>/
            journal.jsonl           # one JSON object per event
            run-01/step-set_content.png
            run-01/result.json
            summary.json
    """

    def __init__(self, root: Path, runset_id: str, agent_id: str | None = None) -> None:
        self.dir = root / runset_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.agent_id = agent_id
        self._f = (self.dir / "journal.jsonl").open("a", encoding="utf-8")

    def event(self, kind: str, **fields: object) -> None:
        if self.agent_id and "agent_id" not in fields:
            fields["agent_id"] = self.agent_id
        row = {"ts": _now(), "t": round(time.time(), 3), "kind": kind, **fields}
        self._f.write(json.dumps(row, default=str) + "\n")
        self._f.flush()
        if kind == "judgment" and fields.get("tokens"):
            # Every paid judgment feeds the daily budget ledger (core.spend). Bookkeeping
            # must never fail a run, so errors here are swallowed.
            try:
                from eeze_agent.core import spend

                spend.record(str(fields.get("agent_id") or self.agent_id or "default"),
                             str(fields.get("model") or ""), int(fields.get("tokens") or 0),
                             source="loop")
            except Exception:  # noqa: BLE001, S110
                pass

    def run_dir(self, run_index: int) -> Path:
        d = self.dir / f"run-{run_index:02d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_png(self, run_index: int, name: str, b64: str) -> Path:
        path = self.run_dir(run_index) / name
        path.write_bytes(base64.b64decode(b64))
        return path

    def save_json(self, run_index: int, name: str, payload: object) -> Path:
        path = self.run_dir(run_index) / name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def close(self) -> None:
        self._f.close()
