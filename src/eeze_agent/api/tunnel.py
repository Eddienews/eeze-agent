"""cloudflared quick-tunnel control — detached (`eeze tunnel start|url|stop`).

Wraps ``cloudflared tunnel --url http://127.0.0.1:<port>`` as a detached process,
captures the public ``*.trycloudflare.com`` URL from its output and keeps it in
``~/.eeze/tunnel.url`` (pid in ``~/.eeze/tunnel.pid``, log in ``~/.eeze/tunnel.log``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from eeze_agent.api import daemon as api_daemon

HOME = Path.home() / ".eeze"
PID_FILE = HOME / "tunnel.pid"
IDENTITY_FILE = HOME / "tunnel.identity.json"
LOG_FILE = HOME / "tunnel.log"
URL_FILE = HOME / "tunnel.url"
DEFAULT_PORT = api_daemon.DEFAULT_PORT
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared() -> str | None:
    """CLOUDFLARED_PATH > PATH > ~/.eeze > ~/Downloads (newest match)."""
    env = os.environ.get("CLOUDFLARED_PATH")
    if env and Path(env).exists():
        return env
    which = shutil.which("cloudflared")
    if which:
        return which
    local = HOME / "cloudflared.exe"
    if local.exists():
        return str(local)
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        matches = sorted(
            (p for p in downloads.glob("cloudflared*")
             if p.is_file() and p.suffix.lower() == ".exe"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if matches:
            return str(matches[0])
    return None


def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _tunnel_identity(pid: int) -> tuple[str, str, str] | None:
    """Identify our quick tunnel, not merely a live/reused PID. Never expose its argv."""
    if pid <= 0:
        return None
    try:
        if sys.platform == "win32":
            script = (
                f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
                "if ($null -eq $p -or $p.Name -notlike 'cloudflared*.exe') { exit 0 }; "
                "$p | Select-Object Name,ExecutablePath,CommandLine,CreationDate "
                "| ConvertTo-Json -Compress"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if result.returncode or not result.stdout.strip():
                return None
            process = json.loads(result.stdout)
            if not isinstance(process, dict):
                return None
            name = str(process.get("Name") or "")
            executable = str(process.get("ExecutablePath") or "")
            command = str(process.get("CommandLine") or "")
            created = str(process.get("CreationDate") or "")
        else:
            proc = Path("/proc") / str(pid)
            name = (proc / "comm").read_text(encoding="utf-8").strip()
            executable = os.readlink(proc / "exe")
            command = (proc / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8")
            # Linux process start time (field 22); the comm field may contain spaces.
            created = (proc / "stat").read_text(encoding="utf-8").rsplit(") ", 1)[1].split()[19]
    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired,
            json.JSONDecodeError):
        return None
    binary = executable.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if not (name.casefold().startswith("cloudflared") and binary.startswith("cloudflared")
            and created and re.search(r"(?:^|\s)tunnel\s+--url\s+\"?http://127\.0\.0\.1:\d+\"?(?=\s|$)",
                                  command, re.IGNORECASE)
            and re.search(r"(?:^|\s)--no-autoupdate(?=\s|$)", command, re.IGNORECASE)):
        return None
    return (created, executable.casefold(), command)


def _fingerprint(identity: tuple[str, str, str]) -> str:
    raw = json.dumps(identity, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _owned_tunnel(pid: int) -> tuple[str, str, str] | None:
    """Match this process instance to the instance persisted by our own start()."""
    identity = _tunnel_identity(pid)
    if identity is None:
        return None
    try:
        saved = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
        if (saved.get("pid") == pid and isinstance(saved.get("fingerprint"), str)
                and hmac.compare_digest(saved["fingerprint"], _fingerprint(identity))):
            return identity
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def start(port: int = DEFAULT_PORT, timeout_s: float = 30.0) -> dict:
    exe = find_cloudflared()
    if not exe:
        return {
            "status": "cloudflared_not_found",
            "hint": "put cloudflared on PATH, set CLOUDFLARED_PATH, or drop it in ~/.eeze/",
        }
    pid = read_pid()
    if pid and api_daemon.pid_alive(pid):
        if _owned_tunnel(pid) is None:
            return {"status": "identity_unverified", "pid": pid}
        return {"status": "already_running", "pid": pid, "url": url().get("url")}

    HOME.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(f"---- start {time.strftime('%Y-%m-%d %H:%M:%S')} -> http://127.0.0.1:{port} ----\n",
                        encoding="utf-8")
    logfh = LOG_FILE.open("ab")
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": logfh,
        "stderr": logfh,
        "close_fds": True,
        "cwd": str(HOME),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = api_daemon.DETACHED_PROCESS | api_daemon.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        **kwargs,
    )
    logfh.close()
    identity = _tunnel_identity(proc.pid)
    for _ in range(8):
        if identity is not None:
            break
        time.sleep(0.25)
        identity = _tunnel_identity(proc.pid)
    if identity is None:
        # Only the Popen handle is safe to terminate when ownership is unverified.
        proc.terminate()
        return {"status": "identity_unverified", "pid": proc.pid}
    try:
        pending = IDENTITY_FILE.with_suffix(".pending")
        pending.write_text(json.dumps({"pid": proc.pid, "fingerprint": _fingerprint(identity)}),
                           encoding="utf-8")
        pending.replace(IDENTITY_FILE)
        URL_FILE.unlink(missing_ok=True)  # a previous instance's URL is not this tunnel's URL
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        proc.terminate()
        return {"status": "identity_unverified", "pid": proc.pid}

    deadline = time.time() + timeout_s
    found = None
    while time.time() < deadline:
        time.sleep(0.5)
        if _owned_tunnel(proc.pid) != identity:
            return {"status": "identity_changed", "pid": proc.pid}
        try:
            text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = URL_RE.search(text)
        if match:
            found = match.group(0)
            break
        if getattr(proc, "poll", lambda: None)() is not None:
            return {"status": "exited", "pid": proc.pid, "log_tail": text[-400:]}

    if _owned_tunnel(proc.pid) != identity:
        return {"status": "identity_changed", "pid": proc.pid}
    if found:
        URL_FILE.write_text(found, encoding="utf-8")
        return {
            "status": "started",
            "pid": proc.pid,
            "url": found,
            "api_responding": api_daemon.http_up(port),
            "log": str(LOG_FILE),
        }
    return {"status": "no_url_yet", "pid": proc.pid, "log": str(LOG_FILE)}


def url() -> dict:
    pid = read_pid()
    if not pid or _owned_tunnel(pid) is None:
        return {"running": False, "pid": pid, "url": None}
    public = None
    try:
        public = URL_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    if not public:  # refresh from the log if the file was lost
        try:
            match = URL_RE.search(LOG_FILE.read_text(encoding="utf-8", errors="replace"))
            if match:
                public = match.group(0)
                URL_FILE.write_text(public, encoding="utf-8")
        except OSError:
            pass
    return {"running": True, "pid": pid, "url": public}


def stop() -> dict:
    pid = read_pid()
    if pid is None:
        return {"status": "not_running", "pid": None}
    identity = _owned_tunnel(pid)
    if identity is None:
        # A recycled PID may belong to the user's browser. Keep metadata for diagnosis.
        return {"status": "identity_unverified", "pid": pid}
    if _tunnel_identity(pid) != identity:
        return {"status": "identity_changed", "pid": pid}
    try:
        if sys.platform == "win32":
            result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                    capture_output=True, text=True, timeout=20, check=False)
            if result.returncode:
                return {"status": "stop_failed", "pid": pid}
        else:
            os.kill(pid, 15)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "stop_failed", "pid": pid}
    if _tunnel_identity(pid) is not None or api_daemon.pid_alive(pid):
        return {"status": "stop_unverified", "pid": pid}
    for f in (PID_FILE, URL_FILE, IDENTITY_FILE):
        try:
            f.unlink()
        except OSError:
            pass
    return {"status": "stopped", "pid": pid}
