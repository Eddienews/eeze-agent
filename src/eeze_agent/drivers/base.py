"""Driver port — the contract the orchestrator uses to observe and act.

Every method receives the run's ``AgentContext`` (ADR-0002): F1 uses it for
app-allowlist checks; later it scopes memory/journaling and per-agent policies.

Contracts learned in F0/F1 spikes (cua-driver 0.28.x, Windows):

- Element addressing: pass ``element_token`` (opaque, per-snapshot). A bare
  ``element_index`` is refused (``snapshot_id_required``).
- Token lifetime: any new capture of the same (pid, window_id) invalidates
  previous tokens (``stale_element_token``). Rule: capture → act immediately.
- ``type_text`` inserts (typing at caret); ``set_value`` replaces the full value.
- Background delivery is the mandatory first rung; escalate to foreground only on
  a returned signal (``suspected_noop`` / ``background_unavailable``).
- Action effects: ``confirmed`` | ``unverifiable`` | ``suspected_noop``; only
  ``confirmed`` means the driver read the result back.
"""

from __future__ import annotations

from typing import Protocol

from eeze_agent.agents.models import AgentContext
from eeze_agent.core.models import ActionOutcome, Observation


class DriverPort(Protocol):
    def launch(
        self, ctx: AgentContext, *, name: str | None = None, aumid: str | None = None
    ) -> dict:
        """Launch an app without focus steal. Returns the raw response (pid, windows)."""
        ...

    def kill(self, ctx: AgentContext, pid: int) -> ActionOutcome: ...

    def list_windows(self, ctx: AgentContext) -> list[dict]:
        """All top-level windows: {title, pid, window_id, is_on_screen, minimized, ...}."""
        ...

    def find_window(self, ctx: AgentContext, needle: str) -> dict | None:
        """First window whose title contains ``needle`` (case-insensitive)."""
        ...

    def main_window(self, ctx: AgentContext, needle: str) -> dict | None:
        """Best main window: on-screen, not minimized, largest area (deterministic)."""
        ...

    def restore_window(self, ctx: AgentContext, pid: int, window_id: int) -> ActionOutcome:
        """Best-effort un-minimize without activating the window."""
        ...

    def capture(
        self,
        ctx: AgentContext,
        pid: int,
        window_id: int,
        *,
        screenshot: bool = False,
        query: str | None = None,
    ) -> Observation: ...

    def set_text(
        self,
        ctx: AgentContext,
        pid: int,
        window_id: int,
        element_token: str,
        text: str,
        *,
        delivery_mode: str = "background",
    ) -> ActionOutcome: ...

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
        """Click by element_token, or in pixel mode with (x, y) window-local coords."""
        ...

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
        """Press-drag-release in window-local screenshot pixels."""
        ...

    def press_key(
        self, ctx: AgentContext, pid: int, window_id: int, key: str
    ) -> ActionOutcome:
        """Press and release a single key (no modifiers — see hotkey)."""
        ...

    def invoke_menu(
        self, ctx: AgentContext, pid: int, window_id: int, path: list[str]
    ) -> ActionOutcome: ...

    def hotkey(
        self,
        ctx: AgentContext,
        pid: int,
        window_id: int,
        keys: list[str],
        *,
        delivery_mode: str = "background",
    ) -> ActionOutcome: ...
