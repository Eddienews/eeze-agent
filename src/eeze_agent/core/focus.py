"""Zero focus-steal audit (F5/M4): prove a GUI run does not steal focus or the cursor.

Windows sampling via user32 (ctypes): foreground window handle + cursor position every
``interval_s``. PASS = the foreground window never changed and the cursor never moved
from its starting point while the task ran. Writes ``artifacts/audits/focus-<stamp>.json``.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

try:  # pragma: no cover — import guard for non-Windows dev boxes
    import ctypes
    from ctypes import wintypes
except Exception:  # noqa: BLE001
    ctypes = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]


@dataclass
class Sample:
    t_ms: int
    hwnd: int
    title: str
    x: int
    y: int


def probe_windows() -> tuple[int, str, int, int]:
    """(foreground hwnd, window title, cursor x, cursor y) — Windows only."""
    if ctypes is None or wintypes is None:
        raise RuntimeError("focus sampling requires Windows (ctypes user32)")
    user32 = ctypes.windll.user32
    hwnd = int(user32.GetForegroundWindow())
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return hwnd, buf.value, int(point.x), int(point.y)


class FocusSampler:
    """Background sampler; ``probe`` is injectable for tests."""

    def __init__(self, interval_s: float = 0.2, probe=None) -> None:
        self.interval_s = interval_s
        self._probe = probe or probe_windows
        self.samples: list[Sample] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0

    def _capture(self) -> None:
        hwnd, title, x, y = self._probe()
        self.samples.append(
            Sample(t_ms=int((time.monotonic() - self._t0) * 1000), hwnd=hwnd, title=title, x=x, y=y)
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._t0 = time.monotonic()
        self._capture()  # baseline sample before the run starts

        def loop() -> None:
            while not self._stop.is_set():
                if self._stop.wait(self.interval_s):
                    break
                try:
                    self._capture()
                except Exception:  # noqa: BLE001, S110 — a sample failure must not kill the audit
                    pass

        self._thread = threading.Thread(target=loop, name="eeze-focus-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        try:
            self._capture()
        except Exception:  # noqa: BLE001, S110 — best-effort final sample
            pass


def analyze(samples: list[Sample]) -> dict:
    """PASS when the foreground hwnd is constant and the cursor never moves."""
    if not samples:
        return {
            "pass": False,
            "reason": "no samples collected",
            "samples": 0,
        }
    baseline = samples[0]
    focus_changes = [
        {"t_ms": s.t_ms, "hwnd": s.hwnd, "title": s.title}
        for s in samples
        if s.hwnd != baseline.hwnd
    ]
    cursor_moves = [
        {"t_ms": s.t_ms, "x": s.x, "y": s.y}
        for s in samples
        if (s.x, s.y) != (baseline.x, baseline.y)
    ]
    max_dx = max((abs(s.x - baseline.x) for s in samples), default=0)
    max_dy = max((abs(s.y - baseline.y) for s in samples), default=0)
    focus_ok = not focus_changes
    cursor_ok = not cursor_moves
    return {
        "pass": focus_ok and cursor_ok,
        "samples": len(samples),
        "duration_ms": samples[-1].t_ms,
        "baseline": {"hwnd": baseline.hwnd, "title": baseline.title, "x": baseline.x, "y": baseline.y},
        "focus_changes": focus_changes[:20],
        "focus_change_count": len(focus_changes),
        "cursor_moves": cursor_moves[:20],
        "cursor_move_count": len(cursor_moves),
        "cursor_max_delta": {"dx": max_dx, "dy": max_dy},
        "focus_pass": focus_ok,
        "cursor_pass": cursor_ok,
    }


def run_focus_audit(
    *,
    task_path: Path,
    repo_root: Path,
    runs: int = 1,
    interval_s: float = 0.2,
    sampler: FocusSampler | None = None,
) -> dict:
    """Run a task and report focus/cursor stability; writes the audit artifact."""
    from eeze_agent.agents.models import AgentContext
    from eeze_agent.agents.registry import load_registry
    from eeze_agent.brains.registry import make_brain
    from eeze_agent.core.journal import RunJournal
    from eeze_agent.core.loop import run_set
    from eeze_agent.core.risk import Policy
    from eeze_agent.core.tasks import load_task
    from eeze_agent.drivers.cua import CuaDriver

    task = load_task(task_path)
    registry = load_registry(repo_root)
    agent = registry.get("default")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    runs_root = repo_root / "artifacts" / "runs"
    runset_id = f"{stamp}-focus-audit"
    out_dir = runs_root / runset_id
    journal = RunJournal(runs_root, runset_id, agent_id=agent.id)
    ctx = AgentContext(agent=agent)
    ctx.runset_id = runset_id

    sam = sampler or FocusSampler(interval_s=interval_s)
    sam.start()
    started = time.monotonic()
    try:
        summary = run_set(
            task=task,
            agent_ctx=ctx,
            driver=CuaDriver(),
            brain=make_brain(agent_id=agent.id, repo_root=repo_root, task=task),
            brain_factory=lambda **kw: make_brain(agent_id=agent.id, repo_root=repo_root, task=task, **kw),
            journal=journal,
            runs=runs,
            out_dir=out_dir,
            policy=Policy(frozenset({"read", "write_local", "install_exec"})),
            task_path=task_path,
        )
    finally:
        sam.stop()
        journal.close()

    report = {
        "task": str(task_path),
        "task_name": task.name,
        "runs": runs,
        "runset_id": runset_id,
        "run_status": summary.get("status"),
        "success_rate": summary.get("success_rate"),
        "wall_s": round(time.monotonic() - started, 2),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **analyze(sam.samples),
    }
    audits = repo_root / "artifacts" / "audits"
    audits.mkdir(parents=True, exist_ok=True)
    artifact = audits / f"focus-{stamp}.json"
    artifact.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact"] = str(artifact)
    report["samples_raw"] = [asdict(s) for s in sam.samples]
    return report
