"""Desktop notifications for pending approvals (Windows toast, no pip deps).

Contract: a notification must never break a run — every failure is swallowed
(logged at WARNING) and callers get ``False``. ``ApprovalWatcher`` is the daemon-side
thread: it toasts once per newly-pending approval and remembers what it toasted in the
settings table, so restarts do not re-notify.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
import threading
from xml.sax.saxutils import escape

log = logging.getLogger("eeze.notify")

APP_NAME = "Eeze Agent"
SETTING_KEY = "notify_approvals"  # "0" disables; missing/anything else = enabled
SEEN_KEY = "notified_approvals"  # comma-joined approval ids already toasted

_PS_SCRIPT = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
    "ContentType = WindowsRuntime] | Out-Null;"
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
    "ContentType = WindowsRuntime] | Out-Null;"
    "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
    "$x.LoadXml([Text.Encoding]::UTF8.GetString("
    "[Convert]::FromBase64String($env:EEZE_TOAST_XML)));"
    "$t = New-Object Windows.UI.Notifications.ToastNotification $x;"
    f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_NAME}')"
    ".Show($t)"
)


def _powershell() -> str | None:
    for name in ("powershell", "powershell.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def toast(title: str, body: str, *, runner=subprocess.run) -> bool:
    """Show a Windows toast notification. Never raises; False = not shown."""
    if sys.platform != "win32":
        return False
    ps = _powershell()
    if ps is None:
        log.warning("no PowerShell found — cannot show a toast")
        return False
    xml = (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{escape(title)}</text><text>{escape(body)}</text>"
        "</binding></visual></toast>"
    )
    env = {
        **os.environ,
        "EEZE_TOAST_XML": base64.b64encode(xml.encode("utf-8")).decode("ascii"),
    }
    try:
        proc = runner(
            [ps, "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
            env=env,
            capture_output=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - env dependent
        log.warning("toast failed: %s", exc)
        return False
    if proc.returncode != 0:
        log.warning("toast failed (rc=%s): %s", proc.returncode, (proc.stderr or b"")[:200])
        return False
    return True


def approval_body(approval: dict) -> str:
    agent = approval.get("agent_id") or "default"
    step = approval.get("step_id") or "a step"
    risk = approval.get("risk_class") or "risk"
    return f"{agent} paused at step '{step}' ({risk}) — approve at http://127.0.0.1:8765/approvals"


class ApprovalWatcher:
    """Toasts once per newly pending approval; dedup persisted in settings."""

    def __init__(
        self,
        store,
        settings,
        *,
        notifier=toast,
        interval_s: float = 20.0,
        title: str = "Eeze needs an approval",
    ) -> None:
        self.store = store
        self.settings = settings
        self.notifier = notifier
        self.interval_s = interval_s
        self.title = title
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def enabled(self) -> bool:
        return (self.settings.get(SETTING_KEY) or "1").strip() != "0"

    def _seen(self) -> set[str]:
        raw = self.settings.get(SEEN_KEY) or ""
        return {item for item in raw.split(",") if item}

    def tick(self) -> list[str]:
        """One pass; returns the approval ids toasted in this pass."""
        if not self.enabled():
            return []
        seen = self._seen()
        sent: list[str] = []
        for approval in self.store.list(status="pending", limit=50):
            approval_id = str(approval.get("id") or "")
            if not approval_id or approval_id in seen:
                continue
            try:
                shown = self.notifier(self.title, approval_body(approval))
            except Exception:
                log.warning("notifier raised", exc_info=True)
                shown = False
            if shown:
                seen.add(approval_id)
                sent.append(approval_id)
        if sent:
            # Keep only ids that still exist in the recent history, so the dedup setting
            # does not grow forever.
            recent = {str(a.get("id") or "") for a in self.store.list(limit=500)}
            self.settings.set(SEEN_KEY, ",".join(sorted(seen & recent)))
        return sent

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.wait(self.interval_s):
                try:
                    self.tick()
                except Exception:
                    log.warning("approval watcher tick failed", exc_info=True)

        self._thread = threading.Thread(target=loop, name="eeze-notify", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


class RoutineFailureWatcher(ApprovalWatcher):
    """Opt-in toast for newly failed routine executions, deduplicated by run ID."""

    SETTING_KEY = "notify_routine_failures"
    SEEN_KEY = "notified_routine_failures"

    def __init__(self, store, settings, *, notifier=toast, interval_s: float = 20.0) -> None:
        super().__init__(store, settings, notifier=notifier, interval_s=interval_s,
                         title="Eeze routine failed")

    def enabled(self) -> bool:
        # On by default (was opt-in and never switched on — failures went unseen for days).
        # Settings stores "0" when the owner turns it off.
        return (self.settings.get(self.SETTING_KEY) or "1").strip() != "0"

    def baseline(self) -> None:
        """Consume completed failures already present when alerts are (re)configured."""
        ids = {str(r["id"]) for r in self.store.runs(limit=1000)
               if r["status"] == "error" and r["ended_at"]}
        self.settings.set(self.SEEN_KEY, ",".join(sorted(self._seen_failures() | ids)))

    def _seen_failures(self) -> set[str]:
        return {item for item in (self.settings.get(self.SEEN_KEY) or "").split(",") if item}

    def tick(self) -> list[str]:
        """Only finished failures; baseline existing runs and skip failures while disabled."""
        failures = [r for r in self.store.runs(limit=1000)
                    if r["status"] == "error" and r["ended_at"]]
        raw = self.settings.get(self.SEEN_KEY)
        ids = {str(r["id"]) for r in failures}
        if raw is None:
            self.baseline()
            return []
        seen = self._seen_failures()
        if not self.enabled():
            if ids - seen:
                self.baseline()
            return []
        sent: list[str] = []
        for run in reversed(failures):
            run_id = str(run["id"])
            if run_id in seen:
                continue
            # Never expose the exception/detail in a desktop notification.
            body = f"Routine {run['routine_id']} failed (run {run_id}) — review /routines"
            try:
                shown = self.notifier(self.title, body)
            except Exception:
                log.warning("routine failure notifier raised", exc_info=True)
                shown = False
            if shown:
                seen.add(run_id)
                sent.append(run_id)
        if sent:
            self.settings.set(self.SEEN_KEY, ",".join(sorted(seen)))
        return sent


def _hours_since(iso: str | None) -> float | None:
    from datetime import UTC, datetime

    try:
        then = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return (datetime.now(UTC) - then).total_seconds() / 3600


class StaleApprovalReminder(ApprovalWatcher):
    """Second nudge for approvals nobody decided: once, after ``remind_after_h`` hours.

    The first toast is easy to miss (the invoice gate waited four days unseen). This one
    also says when the approval will expire, so the owner knows the clock is running.
    Shares the approvals on/off switch with :class:`ApprovalWatcher`.
    """

    REMINDED_KEY = "reminded_approvals"

    def __init__(self, store, settings, *, notifier=toast, interval_s: float = 300.0,
                 remind_after_h: float | None = None) -> None:
        super().__init__(store, settings, notifier=notifier, interval_s=interval_s,
                         title="Eeze is still waiting for you")
        if remind_after_h is None:
            try:
                remind_after_h = float(os.environ.get("EEZE_APPROVAL_REMIND_HOURS") or 4)
            except ValueError:
                remind_after_h = 4.0
        self.remind_after_h = remind_after_h

    def tick(self) -> list[str]:
        if not self.enabled():
            return []
        from eeze_agent.core.approvals import pending_ttl_hours

        reminded = {i for i in (self.settings.get(self.REMINDED_KEY) or "").split(",") if i}
        pending = self.store.list(status="pending", limit=100)
        ttl = pending_ttl_hours()
        sent: list[str] = []
        for approval in pending:
            approval_id = str(approval.get("id") or "")
            age = _hours_since(approval.get("created_at"))
            if not approval_id or approval_id in reminded or age is None:
                continue
            if age < self.remind_after_h:
                continue
            left = f" — expires in about {max(0, round(ttl - age))}h" if ttl else ""
            body = (f"{approval.get('agent_id') or 'default'} has waited {round(age)}h at "
                    f"'{approval.get('step_id') or 'a step'}'{left}. Review at "
                    "http://127.0.0.1:8765/approvals")
            try:
                shown = self.notifier(self.title, body)
            except Exception:
                log.warning("reminder notifier raised", exc_info=True)
                shown = False
            if shown:
                reminded.add(approval_id)
                sent.append(approval_id)
            if len(sent) >= 3:
                break  # at most 3 nudges per pass (no toast storm after an upgrade)
        if sent:
            still = {str(a.get("id") or "") for a in pending}
            self.settings.set(self.REMINDED_KEY, ",".join(sorted(reminded & still)))
        return sent
