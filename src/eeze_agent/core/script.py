"""Script execution for the ``run_script`` step action (creative/tool work).

One command per step, run through the platform shell (``cmd.exe`` on Windows,
``/bin/sh`` elsewhere) with the step's cwd, a hard timeout, and full output written
to a log file inside the runset. The caller (``core.loop``) owns gating: a
``run_script`` step classifies as ``install_exec`` by default, so it pauses for
approval unless the agent policy or a grant allows it.

Honest limits (v1): the timeout kills the shell AND its descendants (``taskkill /T``
on Windows) so a hung grandchild cannot hold the pipes open past the deadline.
The child receives only a small process-bootstrap environment, but there is no
filesystem or network sandbox: a command can still read user files and connect out.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

TAIL_CHARS = 4_000  # kept in ScriptResult for messages/detail
MAX_LOG_CHARS = 2_000_000  # per stream, written to the log file
MAX_ARTIFACTS = 40
MAX_SCAN_ENTRIES = 2_000  # bail out of artifact scanning on huge trees

# Process bootstrap only. Provider/mail/cloud credentials and interpreter hooks are not inherited.
SCRIPT_ENV_ALLOW = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "LANG", "LC_ALL", "LC_CTYPE",
})


def _script_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items()
            if name.upper() in SCRIPT_ENV_ALLOW}


@dataclass
class ScriptResult:
    command: str
    exit_code: int
    timed_out: bool
    duration_ms: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    log_path: Path | None = None
    artifacts: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.exit_code == 0


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def collect_artifacts(
    cwd: Path, since_ts: float, *, exclude: set[str] | None = None, limit: int = MAX_ARTIFACTS
) -> list[dict]:
    """Files under ``cwd`` created/modified since ``since_ts`` (best-effort evidence)."""
    exclude = exclude or set()
    out: list[dict] = []
    scanned = 0
    try:
        walker = cwd.rglob("*")
        for path in walker:
            scanned += 1
            if scanned > MAX_SCAN_ENTRIES or len(out) >= limit:
                break
            try:
                if not path.is_file() or path.name in exclude:
                    continue
                st = path.stat()
            except OSError:
                continue
            if st.st_mtime >= since_ts - 0.5:
                out.append({"path": str(path.relative_to(cwd)), "size": st.st_size})
    except OSError:
        pass
    return out


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the shell AND its descendants.

    Timing out a ``shell=True`` command on Windows kills only ``cmd.exe``; a
    grandchild (e.g. ffmpeg) inherits the stdout/stderr pipes, so draining the pipes
    would block until IT exits — the deadline would not bound wall time. ``taskkill
    /T`` takes the whole subtree down first.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover — last resort
        proc.kill()


def run_command(
    command: str,
    *,
    cwd: Path,
    timeout_s: float,
    log_path: Path | None = None,
) -> ScriptResult:
    """Run one shell command; never raises for command failure (data, not exception)."""
    t0 = time.perf_counter()
    start_wall = time.time()
    timed_out = False
    stdout_raw: bytes = b""
    stderr_raw: bytes = b""
    text_out = ""
    text_err = ""
    code = -1
    kwargs: dict = {}
    if sys.platform == "win32":
        # Never flash a console window: the product's promise is background operation.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(  # shell execution is the point; the risk gate classifies it
            command,
            shell=True,
            cwd=str(cwd),
            env=_script_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )
    except OSError as exc:
        proc = None
        text_err = f"{type(exc).__name__}: {exc}"
    if proc is not None:
        try:
            stdout_raw, stderr_raw = proc.communicate(timeout=max(0.1, float(timeout_s)))
            code = proc.returncode if proc.returncode is not None else -1
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                stdout_raw, stderr_raw = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover — pipes stuck open
                proc.kill()
                stdout_raw, stderr_raw = b"", b""
        text_out = _decode(stdout_raw)
        text_err = _decode(stderr_raw)

    duration_ms = round((time.perf_counter() - t0) * 1000, 1)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        verdict = "TIMED OUT" if timed_out else f"exit={code}"
        with log_path.open("w", encoding="utf-8", errors="replace") as fh:
            fh.write(
                f"$ {command}\n(cwd={cwd} · timeout={timeout_s}s · {verdict} · {duration_ms} ms)\n"
                f"--- stdout ---\n{text_out[:MAX_LOG_CHARS]}\n"
                f"--- stderr ---\n{text_err[:MAX_LOG_CHARS]}\n"
            )
    artifacts = collect_artifacts(
        cwd, start_wall, exclude={log_path.name} if log_path else None
    )
    return ScriptResult(
        command=command,
        exit_code=code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        stdout_tail=text_out[-TAIL_CHARS:],
        stderr_tail=text_err[-TAIL_CHARS:],
        log_path=log_path,
        artifacts=artifacts,
    )
