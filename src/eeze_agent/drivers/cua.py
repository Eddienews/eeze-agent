"""cua-driver adapter — drives the CLI (``cua-driver call <tool> '<json>'``).

Implements the DriverPort contract (see ``drivers/base.py`` for the semantics and
the F0/F1 findings). This module centralizes the token-discipline rules and
normalizes driver responses into our models; the loop never shells out directly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time

from eeze_agent.agents.models import AgentContext
from eeze_agent.core.models import ActionOutcome, Observation


class CuaDriverError(RuntimeError):
    """Transport-level failure (binary missing, timeout, non-JSON output)."""


class CuaDriver:
    def __init__(self, binary: str | None = None, timeout: int = 90) -> None:
        self.binary = binary or shutil.which("cua-driver") or "cua-driver"
        self.timeout = timeout

    # -- daemon --------------------------------------------------------------
    def daemon_running(self) -> bool:
        proc = subprocess.run(
            [self.binary, "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return "not running" not in (proc.stdout + proc.stderr).lower()

    def ensure_daemon(self, wait_s: float = 12.0) -> None:
        """Start `cua-driver serve` detached if the daemon isn't running."""
        if self.daemon_running():
            return
        flags = 0x00000008 | 0x01000000  # DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB
        try:
            subprocess.Popen(
                [self.binary, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        except OSError:
            subprocess.Popen(
                [self.binary, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if self.daemon_running():
                return
            time.sleep(0.5)
        raise CuaDriverError("cua-driver daemon did not start")

    # -- low level -----------------------------------------------------------
    def call(self, tool: str, payload: dict | None = None, timeout: int | None = None) -> dict:
        """Invoke one tool; retries once after reviving a dead daemon."""
        try:
            return self._call_once(tool, payload, timeout)
        except CuaDriverError as exc:
            msg = str(exc).lower()
            if any(
                marker in msg
                for marker in ("daemon is not running", "daemon closed connection", "named pipe")
            ):
                self.ensure_daemon()
                return self._call_once(tool, payload, timeout)
            raise

    def _call_once(self, tool: str, payload: dict | None, timeout: int | None) -> dict:
        cmd = [self.binary, "call", tool] + ([json.dumps(payload)] if payload else [])
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CuaDriverError(f"{tool}: timeout after {timeout or self.timeout}s") from exc
        dt = round((time.perf_counter() - t0) * 1000, 1)
        if proc.returncode != 0:
            err = (proc.stderr.strip() or proc.stdout.strip())[:300]
            raise CuaDriverError(f"{tool}: exit {proc.returncode}: {err}")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise CuaDriverError(f"{tool}: non-JSON output: {proc.stdout[:200]!r}") from exc
        if isinstance(data, dict):
            data["_ms"] = dt
            return data
        return {"_data": data, "_ms": dt}

    @staticmethod
    def _outcome(tool: str, raw: dict) -> ActionOutcome:
        refusal = raw.get("refusal") or {}
        return ActionOutcome(
            tool=tool,
            status=raw.get("status"),
            effect=raw.get("effect"),
            route=raw.get("route"),
            code=refusal.get("code"),
            refusal_message=refusal.get("message"),
            ms=float(raw.get("_ms") or 0.0),
            raw=raw,
        )

    # -- DriverPort ----------------------------------------------------------
    def launch(
        self, ctx: AgentContext, *, name: str | None = None, aumid: str | None = None
    ) -> dict:
        payload: dict = {}
        if aumid:
            payload["aumid"] = aumid
        elif name:
            payload["name"] = name
        apps = (ctx.agent.permissions or {}).get("apps", ["*"])
        if apps != ["*"]:
            target = (aumid or name or "").lower()
            if not any(str(a).lower() in target for a in apps):
                raise CuaDriverError(
                    f"agent {ctx.agent_id!r} may not launch {aumid or name!r} "
                    f"(apps allowlist: {apps})"
                )
        return self.call("launch_app", payload)

    def kill(self, ctx: AgentContext, pid: int) -> ActionOutcome:
        """Terminate the app; falls back to a targeted taskkill when refused.

        The driver refuses (``foreign_process_termination_denied``) processes it
        cannot prove were launched by the current runtime — e.g. leftovers from a
        previous daemon generation (seen after a driver update). The pid comes
        from our own launch, so a targeted taskkill (never by image name) is safe.
        """
        raw = self.call("kill_app", {"pid": pid})
        outcome = self._outcome("kill_app", raw)
        if outcome.code == "foreign_process_termination_denied":
            proc = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                text=True,
                check=False,
            )
            message = (proc.stdout or proc.stderr or "").strip()[:160]
            outcome.raw = {**raw, "taskkill": message, "taskkill_ok": proc.returncode == 0}
            if proc.returncode == 0:
                outcome.status = "fallback_ok"
                outcome.code = None
        return outcome

    def list_windows(self, ctx: AgentContext) -> list[dict]:
        raw = self.call("list_windows")
        return raw.get("_legacy_windows", []) or raw.get("windows", []) or []

    def find_window(self, ctx: AgentContext, needle: str) -> dict | None:
        needle_l = needle.lower()
        for w in self.list_windows(ctx):
            if needle_l in str(w.get("title", "")).lower():
                return w
        return None

    def main_window(self, ctx: AgentContext, needle: str) -> dict | None:
        """Best main window for an app: on-screen, not minimized, largest area.

        Win11 Notepad session-restore exposes every restored tab as its own
        top-level window stub for the same pid; a naive first-match can land on
        an off-screen/minimized stub (F1 finding). This scores candidates.
        """
        matches = [
            w
            for w in self.list_windows(ctx)
            if needle.lower() in str(w.get("title", "")).lower()
        ]
        if not matches:
            return None

        def score(w: dict) -> tuple[int, int]:
            on_screen = 1 if w.get("is_on_screen") else 0
            visible = 0 if w.get("minimized") else 1
            area = int(w.get("width") or 0) * int(w.get("height") or 0)
            return (on_screen * visible, area)

        return max(matches, key=score)

    def restore_window(self, ctx: AgentContext, pid: int, window_id: int) -> ActionOutcome:
        """Un-minimize a window.

        Clicks are refused while minimized (even on the Maximize button) and
        set_window_frame demands bring_to_front — so the sanctioned recovery is an
        explicit activation. This is the ONE place we accept a brief focus change:
        it only fires when someone minimized the agent's window.
        """
        return self._outcome(
            "restore_window",
            self.call("bring_to_front", {"pid": pid, "window_id": window_id}),
        )

    def capture(
        self,
        ctx: AgentContext,
        pid: int,
        window_id: int,
        *,
        screenshot: bool = False,
        query: str | None = None,
    ) -> Observation:
        payload: dict = {
            "pid": pid,
            "window_id": window_id,
            "include_screenshot": bool(screenshot),
        }
        if query:
            payload["query"] = query
        raw = self.call("get_window_state", payload)
        return Observation(
            pid=raw.get("pid", pid),
            window_id=raw.get("window_id", window_id),
            window_title=raw.get("window_title"),
            app_name=raw.get("app_name"),
            snapshot_id=raw.get("snapshot_id"),
            degraded=raw.get("degraded"),
            degraded_reason=raw.get("degraded_reason"),
            escalation=raw.get("escalation"),
            elements=raw.get("elements", []) or [],
            screenshot_png_b64=raw.get("screenshot_png_b64"),
            ms=float(raw.get("_ms") or 0.0),
        )

    def set_text(
        self,
        ctx: AgentContext,
        pid: int,
        window_id: int,
        element_token: str,
        text: str,
        *,
        delivery_mode: str = "background",
    ) -> ActionOutcome:
        return self._outcome(
            "set_value",
            self.call(
                "set_value",
                {"pid": pid, "window_id": window_id, "element_token": element_token, "value": text},
            ),
        )

    def type_text(
        self, ctx: AgentContext, pid: int, window_id: int, text: str, element_token: str | None = None
    ) -> ActionOutcome:
        payload: dict = {"pid": pid, "window_id": window_id, "text": text}
        if element_token:
            payload["element_token"] = element_token
        return self._outcome("type_text", self.call("type_text", payload))

    def click(
        self,
        ctx: AgentContext,
        pid: int,
        window_id: int,
        element_token: str | None = None,
        *,
        x: int | None = None,
        y: int | None = None,
        count: int = 1,
        delivery_mode: str = "background",
    ) -> ActionOutcome:
        payload: dict = {
            "pid": pid,
            "window_id": window_id,
            "count": count,
            "delivery_mode": delivery_mode,
        }
        if element_token is not None:
            payload["element_token"] = element_token
        if x is not None and y is not None:
            payload["x"] = x
            payload["y"] = y
        return self._outcome("click", self.call("click", payload))

    def drag(
        self,
        ctx: AgentContext,
        pid: int,
        window_id: int,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        *,
        delivery_mode: str = "background",
    ) -> ActionOutcome:
        return self._outcome(
            "drag",
            self.call(
                "drag",
                {
                    "pid": pid,
                    "window_id": window_id,
                    "from_x": from_x,
                    "from_y": from_y,
                    "to_x": to_x,
                    "to_y": to_y,
                    "delivery_mode": delivery_mode,
                },
            ),
        )

    def press_key(
        self, ctx: AgentContext, pid: int, window_id: int, key: str
    ) -> ActionOutcome:
        return self._outcome(
            "press_key", self.call("press_key", {"pid": pid, "window_id": window_id, "key": key})
        )

    def invoke_menu(
        self, ctx: AgentContext, pid: int, window_id: int, path: list[str]
    ) -> ActionOutcome:
        return self._outcome(
            "invoke_menu",
            self.call("invoke_menu", {"pid": pid, "window_id": window_id, "path": path}),
        )

    def hotkey(
        self,
        ctx: AgentContext,
        pid: int,
        window_id: int,
        keys: list[str],
        *,
        delivery_mode: str = "background",
    ) -> ActionOutcome:
        return self._outcome(
            "hotkey",
            self.call(
                "hotkey",
                {
                    "pid": pid,
                    "window_id": window_id,
                    "keys": keys,
                    "delivery_mode": delivery_mode,
                },
            ),
        )
