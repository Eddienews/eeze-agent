"""Detached API daemon control — survives the GUI (`eeze api start|stop|status`).

The daemon is a plain uvicorn process launched with ``DETACHED_PROCESS |
CREATE_NEW_PROCESS_GROUP`` on Windows (no console; not tied to the parent's
lifetime), stdout/stderr appended to ``~/.eeze/api.log``. Its pid lives in
``~/.eeze/api.pid``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from eeze_agent.core import procs as _procs

HOME = Path.home() / ".eeze"
PID_FILE = HOME / "api.pid"
LOG_FILE = HOME / "api.log"
DEFAULT_PORT = 8765
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    return _procs.pid_alive(pid)


def http_up(port: int = DEFAULT_PORT, timeout: float = 2.0) -> bool:
    try:
        # A3 protects /api/system/status; readiness must never depend on operator data.
        with httpx.Client(timeout=timeout) as client:
            health = client.get(f"http://127.0.0.1:{port}/api/health")
            body = health.json() if health.status_code == 200 else {}
            if isinstance(body, dict) and body.get("service") == "eeze":
                return True  # "degraded" (scheduler thread down) still means the API is up
            # Recognize an already-running pre-A3 daemon during a controlled upgrade.
            legacy = client.get(f"http://127.0.0.1:{port}/api/system/status")
            return legacy.status_code == 200 and "daemon" in legacy.json()
    except (httpx.HTTPError, ValueError):
        return False


def port_pid(port: int = DEFAULT_PORT) -> int | None:
    """PID currently LISTENING on ``port`` (Windows netstat), if any."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        parts = line.split()
        if (
            len(parts) >= 5
            and parts[0].upper() == "TCP"
            and parts[3].upper() == "LISTENING"
            and parts[1].endswith(f":{port}")
        ):
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


def start(host: str = "127.0.0.1", port: int = DEFAULT_PORT, serve_ui: bool | None = None) -> dict:
    """Launch the API detached; returns status incl. readiness."""
    existing = read_pid()
    if existing and pid_alive(existing) and http_up(port):
        return {"status": "already_running", "pid": existing, "port": port,
                "url": f"http://127.0.0.1:{port}"}
    if http_up(port):  # someone else (user terminal) is serving the port
        holder = port_pid(port)
        return {"status": "already_running", "pid": holder, "port": port,
                "url": f"http://127.0.0.1:{port}", "note": "not started by eeze daemon"}

    HOME.mkdir(parents=True, exist_ok=True)
    code = (
        "import uvicorn\n"
        "from eeze_agent.api.app import create_app\n"
        f"uvicorn.run(create_app(serve_ui={serve_ui!r}, scheduler=True), host={host!r}, port={port}, "
        "log_level='warning')\n"
    )
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"---- start {time.strftime('%Y-%m-%d %H:%M:%S')} host={host} port={port} ----\n")
    logfh = LOG_FILE.open("ab")
    kwargs: dict = {
        "cwd": str(_repo_root()),
        "stdin": subprocess.DEVNULL,
        "stdout": logfh,
        "stderr": logfh,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen([sys.executable, "-c", code], **kwargs)
    logfh.close()
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")

    responding = False
    for _ in range(40):  # up to ~10 s
        time.sleep(0.25)
        if http_up(port, timeout=1.5):
            responding = True
            break
    return {
        "status": "started" if responding else "started_not_responding",
        "pid": proc.pid,
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "log": str(LOG_FILE),
    }


def stop(port: int = DEFAULT_PORT) -> dict:
    """Kill the daemon tree (pidfile + whatever holds the port)."""
    pid = read_pid()
    targets: list[int] = []
    skipped: list[int] = []
    # A stale pidfile (after a reboot) can name a *different* program that reused the
    # PID — only kill it if it still looks like our Python daemon.
    if pid and pid_alive(pid):
        if _procs.looks_like_python(pid):
            targets.append(pid)
        else:
            skipped.append(pid)
    holder = port_pid(port)
    if holder and holder not in targets and _procs.looks_like_python(holder):
        targets.append(holder)
    killed: list[int] = []
    for t in targets:
        try:
            if sys.platform == "win32":
                # No /T: routine/resume workers are detached children of the daemon and
                # must be allowed to finish (or be reaped as orphans), not killed mid-write.
                subprocess.run(["taskkill", "/F", "/PID", str(t)],
                               capture_output=True, text=True, timeout=20, check=False)
            else:
                os.kill(t, 15)
            killed.append(t)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        PID_FILE.unlink()
    except OSError:
        pass
    out = {"status": "stopped" if killed else "not_running", "killed": killed, "port": port}
    if skipped:
        out["skipped_foreign_pids"] = skipped
    return out


def status(port: int = DEFAULT_PORT) -> dict:
    pid = read_pid()
    alive = bool(pid and pid_alive(pid))
    up = http_up(port)
    holder = port_pid(port)
    return {
        "running": bool(alive or up),
        "pid": pid if alive else holder,
        "port": port,
        "responding": up,
        "url": f"http://127.0.0.1:{port}",
        "pid_file": str(PID_FILE),
        "log": str(LOG_FILE),
    }
