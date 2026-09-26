"""Pilot readiness checks (F6): everything tomorrow's scheduled run depends on.

Pure-ish: every external touch (daemon status, IMAP probe, paths, env) is injectable so
tests never hit the network or the real daemon. The CLI prints the checklist and exits
non-zero when a critical item is off.
"""

from __future__ import annotations

import os
from pathlib import Path

from eeze_agent.core.envfile import read_env


def _autostart_path(startup_dir: Path) -> Path:
    return startup_dir / "Eeze Agent service.cmd"


def pilot_checks(
    *,
    repo_root: Path,
    home: Path | None = None,
    startup_dir: Path | None = None,
    env: dict[str, str] | None = None,
    daemon_status_fn=None,
    imap_probe_fn=None,
    routine_store=None,
) -> dict:
    """Run the readiness checklist; returns {ok, checks: [{name, ok, critical, detail}]}."""
    home = home or Path.home() / ".eeze"
    startup_dir = startup_dir or Path(
        os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))
    ) / "Microsoft/Windows/Start Menu/Programs/Startup"
    dotenv = read_env(repo_root / ".env")

    def env_value(key: str) -> str | None:
        if env is not None and key in env:
            return env[key]
        return os.environ.get(key) or dotenv.get(key)

    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, *, critical: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "critical": critical, "detail": detail})

    # 1. daemon
    if daemon_status_fn is None:
        from eeze_agent.api.daemon import status as daemon_status_fn  # type: ignore[assignment]

    try:
        status = daemon_status_fn()
        up = bool(status.get("running") and status.get("responding"))
        add("Daemon", up, f"running={status.get('running')} responding={status.get('responding')} pid={status.get('pid')}")
    except Exception as exc:  # noqa: BLE001 — reported as a failed check
        add("Daemon", False, f"status failed: {exc}")

    # 2. autostart entry (so schedules fire after a login)
    entry = _autostart_path(startup_dir)
    add("Autostart", entry.exists(), str(entry), critical=False)

    # 3. invoices routine armed
    if routine_store is None:
        from eeze_agent.core.routines import RoutineStore

        routine_store = RoutineStore()
    try:
        routines = routine_store.list()
        armed = [r for r in routines if r["enabled"] and r["id"] == "invoices"]
        if armed:
            add("Routine 'invoices'", True, f"enabled · next run {armed[0]['next_run_at']}")
        else:
            enabled = [r["id"] for r in routines if r["enabled"]]
            add("Routine 'invoices'", False, f"not enabled — enabled routines: {enabled or 'none'}")
    except Exception as exc:  # noqa: BLE001
        add("Routine 'invoices'", False, f"store failed: {exc}")

    # 4. mailbox credentials + live probe (read-only)
    user = env_value("EEZE_IMAP_USER")
    password = env_value("EEZE_IMAP_APP_PASSWORD")
    if not (user and password):
        add("Mailbox", False, "EEZE_IMAP_USER / EEZE_IMAP_APP_PASSWORD not set")
    else:
        if imap_probe_fn is None:
            from eeze_agent.verticals.invoices.imap_source import (
                test_login as imap_probe_fn,  # type: ignore[assignment]
            )

        try:
            info = imap_probe_fn(env_value("EEZE_IMAP_HOST") or "imap.gmail.com", user, password)
            add("Mailbox", True, f"{user} · {info.get('messages')} messages in {info.get('folder')}")
        except Exception as exc:  # noqa: BLE001 — readable failure for the checklist
            add("Mailbox", False, f"probe failed: {exc}")

    # 5. brain/planner configs (extraction + gated email depend on them)
    extract_key = env_value("EEZE_EXTRACT_API_KEY")
    add("Extraction model", bool(extract_key), "EEZE_EXTRACT_* configured" if extract_key else "EEZE_EXTRACT_API_KEY missing")
    planner_key = env_value("EEZE_PLANNER_API_KEY")
    add("Planner key", bool(planner_key), "EEZE_PLANNER_* configured" if planner_key else "EEZE_PLANNER_API_KEY missing", critical=False)

    # 6. which ENGINE the loop would use right now (P1: codex subscription is local-only)
    try:
        from eeze_agent.brains.registry import resolve_brain_name

        name = resolve_brain_name(repo_root=repo_root)
    except Exception as exc:  # noqa: BLE001 — a broken brain name is exactly what a check is for
        name = f"? ({exc})"
    detail = f"brain={name}"
    if name == "codex":
        from shutil import which

        from eeze_agent.brains.codex import codex_model_for_tier, paid_fallback_enabled

        binary = which(env_value("EEZE_CODEX_BIN") or "codex")
        ladder = "paid fallback ON" if paid_fallback_enabled() else "subscription-only"
        detail = (
            f"brain=codex (local-only; {ladder}) · "
            f"routine={codex_model_for_tier('routine')} · hard={codex_model_for_tier('hard')} · "
            f"cli={'found' if binary else 'MISSING'}"
        )
    add("Loop brain", not name.startswith("?"), detail, critical=False)

    ok = all(c["ok"] for c in checks if c["critical"])
    return {"ok": ok, "checks": checks}
