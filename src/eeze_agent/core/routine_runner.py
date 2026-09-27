"""Routine execution (F4): run one routine to completion — or pause at the F2 gate.

``invoices``: pull the mailbox (read-only) → verified ledger + anomalies; an optional
``email_summary`` step ships as ``external_send`` and therefore waits for approval —
approving it resumes via ``eeze routines resume <approval_id>`` and sends the files.

``task``: run a task YAML through the gated loop (pauses resume with
``eeze run --resume`` as usual).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from eeze_agent.agents.models import AgentContext
from eeze_agent.agents.registry import load_registry
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.journal import RunJournal
from eeze_agent.core.loop import run_set
from eeze_agent.core.risk import RISK_ORDER, Policy, policy_for_agent
from eeze_agent.core.routines import (
    RoutineStore,
    log_line,
    path_safe,
    routine_log_path,
    task_routine_status,
)


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _policy_for(routine: dict, agent) -> Policy:
    """Agent policy + explicit per-routine allowance (validated, never silent)."""
    base = policy_for_agent(agent.permissions)
    extra = [str(x) for x in (routine.get("params", {}).get("allow") or [])]
    unknown = [x for x in extra if x not in RISK_ORDER]
    if unknown:
        raise ValueError(f"unknown risk classes in routine allow: {unknown}")
    if not extra:
        return base
    return Policy(frozenset(base.allowed | set(extra)))


def _digest(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _routine_fingerprint(routine: dict) -> str:
    # Schedule and last_run_at change naturally while an approval is pending.
    return _digest({key: routine.get(key) for key in ("id", "kind", "agent_id", "params")})


def _invoice_attachments(out_dir: Path) -> dict[str, bytes]:
    root = out_dir.resolve()
    files = {}
    for name in ("ledger.csv", "anomalies.md"):
        path = out_dir / name
        if not path.is_file() or path.resolve().parent != root:
            raise ValueError(f"invoice attachment missing or outside output directory: {name}")
        files[name] = path.read_bytes()
    return files


def _resume_digest(payload: dict) -> str:
    return _digest({k: v for k, v in payload.items() if k not in {"approval_id", "resume_argv"}})


# ---------------- kind: invoices ----------------


def run_invoices(routine: dict, *, repo_root: Path, approvals: ApprovalStore, agent, log: Path, brain=None, run_id: str = "") -> dict:
    from eeze_agent.verticals.invoices.imap_source import (
        ImapConfigError,
        ImapError,
        pull_pdf_attachments,
    )
    from eeze_agent.verticals.invoices.pipeline import run_vertical

    params = routine.get("params", {})
    out_dir = repo_root / "artifacts" / "routines" / path_safe(routine["id"]) / _stamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    inbox = out_dir / "inbox"

    log_line(log, f"pull: search={params.get('search', 'ALL')!r}")
    try:
        pull = pull_pdf_attachments(inbox, search=params.get("search", "ALL"))
    except (ImapConfigError, ImapError) as exc:
        return {"status": "error", "error": f"inbox pull failed: {exc}"}
    log_line(log, f"pull: fetched={pull.fetched} attachments={pull.attachments}")

    if brain is None:
        from eeze_agent.verticals.invoices.llm import ExtractionBrain

        brain = ExtractionBrain()
    if hasattr(brain, "budget_agent"):
        brain.budget_agent = agent  # the routine's agent pays (and is capped)
    summary = run_vertical(inbox, out_dir, brain=brain)
    log_line(
        log,
        f"ledger: files={summary['files']} ok={summary['ok']} flagged={summary['flagged']} "
        f"anomalies={summary['anomalies']}",
    )
    result: dict = {
        "status": "ok",
        "out_dir": str(out_dir),
        "pull": {"fetched": pull.fetched, "attachments": pull.attachments},
        "ledger": {
            k: summary.get(k) for k in ("files", "ok", "flagged", "anomalies", "ledger", "anomalies_report")
        },
    }
    if params.get("email_summary"):
        result.update(_maybe_send_summary(routine, out_dir, summary, approvals, agent, log, run_id=run_id))
    return result


def _maybe_send_summary(
    routine: dict, out_dir: Path, summary: dict, approvals: ApprovalStore, agent, log: Path, *, run_id: str = ""
) -> dict:
    params = routine.get("params", {})
    policy = _policy_for(routine, agent)
    granted = approvals.active_grant(agent.id, "external_send", f"routine:{routine['id']}")
    if not policy.allows("external_send") and granted is None:
        to = str(params.get("email_to") or os.environ.get("EEZE_IMAP_USER") or "")
        if not to:
            return {"status": "error", "error": "missing email_to and mail sender"}
        subject = _summary_subject(summary)
        files = _invoice_attachments(out_dir)
        state_payload = {
            "kind": "routine",
            "routine_id": routine["id"],
            "routine_run_id": run_id,
            "out_dir": str(out_dir.resolve()),
            "email_to": to,
            "email_subject": subject,
            "completed": {
                "ledger": {k: summary.get(k) for k in ("files", "ok", "flagged", "anomalies")}
            },
            "binding": {
                "routine_fingerprint": _routine_fingerprint(routine),
                "attachments": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            },
        }
        approval_id = approvals.request(
            runset_id=f"routine-{path_safe(routine['id'])}-{_stamp()}",
            task=f"routine:{routine['id']}",
            task_path="",
            agent_id=agent.id,
            run_index=1,
            step_id="email-summary",
            step_index=0,
            action="email_summary",
            risk_class="external_send",
            reason="routine email_summary is gated (sends externally)",
            payload={"to": to, "subject": subject},
            action_digest=_resume_digest(state_payload),
            run_state=lambda aid: {
                **state_payload, "approval_id": aid, "resume_argv": ["routines", "resume", aid],
            },
        )
        log_line(log, f"email_summary GATED — approval {approval_id}")
        return {"status": "needs_approval", "approval_id": approval_id}

    info = _send_summary(params, out_dir, summary, log)
    return {"status": "ok" if info.get("sent") else "error", "email": info}


def _summary_subject(summary: dict) -> str:
    return (
        f"Eeze invoices — {time.strftime('%Y-%m-%d %H:%M')} · "
        f"{summary.get('files')} files, {summary.get('flagged')} flagged"
    )


def _send_summary(
    params: dict, out_dir: Path, summary: dict, log: Path, *,
    subject: str | None = None, attachments: dict[str, bytes] | None = None,
) -> dict:
    import smtplib
    from email.message import EmailMessage

    user = os.environ.get("EEZE_IMAP_USER")
    password = (os.environ.get("EEZE_IMAP_APP_PASSWORD") or "").replace(" ", "")
    to = str(params.get("email_to") or user or "")
    if not (user and password and to):
        return {"sent": False, "error": "missing mail credentials or email_to"}

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject or _summary_subject(summary)
    msg.set_content(
        "Invoice routine summary\n\n"
        f"files: {summary.get('files')} · ok: {summary.get('ok')} · "
        f"flagged: {summary.get('flagged')} · anomalies: {summary.get('anomalies')}\n\n"
        "The verified ledger and the anomaly report are attached.\n"
    )
    for name in ("ledger.csv", "anomalies.md"):
        path = Path(out_dir) / name
        data = attachments[name] if attachments is not None else (path.read_bytes() if path.exists() else None)
        if data is not None:
            msg.add_attachment(
                data,
                maintype="text",
                subtype="csv" if name.endswith(".csv") else "markdown",
                filename=name,
            )
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 — network/SMTP failures are data here
        log_line(log, f"email_summary FAILED: {type(exc).__name__}: {exc}")
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
    log_line(log, f"email_summary SENT to {to}")
    return {"sent": True, "to": to}


def run_resume(approval_id: str, *, repo_root: Path, approvals: ApprovalStore, log: Path) -> dict:
    """Continue a bound invoice email once; legacy/unverifiable states fail closed."""
    state = approvals.run_state_for(approval_id)
    if state is None:
        return {"status": "error", "error": f"no run state for {approval_id}"}
    try:
        payload = json.loads(state["payload"])
    except (TypeError, ValueError):
        return {"status": "error", "error": "invalid routine resume state"}
    if payload.get("kind") != "routine":
        return {"status": "error", "error": "not a routine resume state"}
    approval = approvals.get(approval_id)
    if approval is None or approval.get("status") != "approved":
        return {
            "status": "error",
            "error": f"approval {approval_id} is {(approval or {}).get('status')!r} — approve it first",
        }
    try:
        routine = RoutineStore(approvals.path).get(payload["routine_id"])
        binding = payload["binding"]
        out_dir = Path(payload["out_dir"])
        if (state["status"] != "waiting" or not routine or routine["kind"] != "invoices"
                or not routine["params"].get("email_summary")
                or _routine_fingerprint(routine) != binding["routine_fingerprint"]
                or payload["email_to"] != str(routine["params"].get("email_to")
                                              or os.environ.get("EEZE_IMAP_USER") or "")
                or not payload["email_to"] or out_dir.resolve() != out_dir
                or not out_dir.resolve().is_relative_to(repo_root.resolve())
                or payload["approval_id"] != approval_id
                or payload["resume_argv"] != ["routines", "resume", approval_id]
                or approval["agent_id"] != routine["agent_id"]
                or approval["task"] != f"routine:{routine['id']}"
                or approval["action"] != "email_summary"
                or approval["risk_class"] != "external_send"
                or json.loads(approval["payload"]) != {
                    "to": payload["email_to"], "subject": payload["email_subject"]
                }):
            raise ValueError("invoice approval identity changed")
        files = _invoice_attachments(out_dir)
        if {name: hashlib.sha256(data).hexdigest() for name, data in files.items()} != binding["attachments"]:
            raise ValueError("invoice attachments changed")
        approvals.claim_resume(approval_id, payload, _resume_digest(payload))
    except (KeyError, TypeError, ValueError, OSError) as exc:
        log_line(log, f"resume {approval_id} refused: {exc}")
        return {"status": "error", "error": "invoice approval no longer matches; request a new approval"}

    summary = dict(payload["completed"]["ledger"])
    info = _send_summary(
        {"email_to": payload["email_to"]}, out_dir, summary, log,
        subject=payload["email_subject"], attachments=files,
    )
    log_line(log, f"resume {approval_id}: email {'sent' if info.get('sent') else 'failed'}")
    if payload.get("routine_run_id"):
        RoutineStore(approvals.path).end_run(
            str(payload["routine_run_id"]), str(payload["routine_id"]),
            status="ok" if info.get("sent") else "error",
            detail={"resumed": True, "email": info}, approval_id=approval_id,
        )
    return {"status": "ok" if info.get("sent") else "error", "email": info}


# ---------------- kind: task ----------------


def run_task(routine: dict, *, repo_root: Path, approvals: ApprovalStore, agent, log: Path, brain=None, run_id: str = "") -> dict:
    from eeze_agent.brains.registry import make_brain
    from eeze_agent.core.tasks import load_task
    from eeze_agent.drivers.cua import CuaDriver

    params = routine.get("params", {})
    task_path = Path(str(params.get("task_path") or ""))
    if not task_path.exists():
        return {"status": "error", "error": f"task file not found: {task_path}"}
    task = load_task(task_path)
    runs_root = repo_root / "artifacts" / "runs"
    runset_id = _stamp() + f"-routine-{path_safe(routine['id'])}"
    out_dir = runs_root / runset_id
    journal = RunJournal(runs_root, runset_id, agent_id=agent.id)
    ctx = AgentContext(agent=agent)
    ctx.runset_id = runset_id
    summary = run_set(
        task=task,
        agent_ctx=ctx,
        driver=CuaDriver(),
        brain=brain if brain is not None else make_brain(agent_id=agent.id, repo_root=repo_root, task=task),
        brain_factory=lambda **kw: make_brain(agent_id=agent.id, repo_root=repo_root, task=task, **kw),
        journal=journal,
        runs=int(params.get("runs") or 1),
        out_dir=out_dir,
        demo=bool(params.get("demo")),
        policy=_policy_for(routine, agent),
        approvals=approvals,
        task_path=task_path,
        extra_state={"routine_run_id": run_id, "routine_id": routine["id"]},
    )
    journal.close()
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {
        "status": task_routine_status(summary),
        "runset_id": runset_id,
        "approval_id": summary.get("approval_id"),
        "summary": {k: summary.get(k) for k in ("status", "success_rate", "approval_id")},
    }


# ---------------- top level ----------------


def run_routine(routine_id: str, *, repo_root: Path, home: Path, brain=None) -> dict:
    """Execute one routine by id; records the run; never raises for routine-level errors."""
    store = RoutineStore()
    approvals = ApprovalStore()
    routine = store.get(routine_id)
    if routine is None:
        return {"status": "error", "error": f"unknown routine: {routine_id!r}"}
    registry = load_registry(repo_root)
    agent = registry.get(routine.get("agent_id") or "default")
    log = routine_log_path(home, routine_id)
    run_id = store.start_run(routine_id, log_path=str(log))
    log_line(log, f"run {run_id} start (kind={routine['kind']})")
    result: dict
    try:
        if routine["kind"] == "invoices":
            result = run_invoices(
                routine, repo_root=repo_root, approvals=approvals, agent=agent, log=log, brain=brain, run_id=run_id
            )
        elif routine["kind"] == "task":
            result = run_task(routine, repo_root=repo_root, approvals=approvals, agent=agent, log=log, brain=brain, run_id=run_id)
        else:
            result = {"status": "error", "error": f"unknown routine kind: {routine['kind']!r}"}
    except Exception as exc:  # noqa: BLE001 — record, never crash the scheduler's child silently
        result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        log_line(log, f"run crashed: {result['error']}")
    status = str(result.get("status") or "error")
    store.end_run(run_id, routine_id, status=status, detail=result, approval_id=result.get("approval_id"))
    log_line(log, f"run {run_id} end: {status}")
    _record_on_mission(routine_id, result, home=home, repo_root=repo_root)
    return result


def _record_on_mission(routine_id: str, result: dict, *, home: Path, repo_root: Path) -> None:
    """A scheduled or folder-watch run of a mission shows on the mission's card too."""
    if not routine_id.startswith("mission:") or not result.get("runset_id"):
        return
    from eeze_agent.core.missions import MissionError, MissionStore

    status = str(result.get("status") or "error")
    try:
        MissionStore(home).record_run(
            routine_id.split(":", 1)[1],
            runset_id=str(result["runset_id"]),
            status="done" if status == "ok" else status,
            approval_id=result.get("approval_id"),
            out_dir=str(Path(repo_root) / "artifacts" / "runs" / str(result["runset_id"])),
        )
    except (MissionError, OSError):
        pass  # the mission was deleted meanwhile; the routine run is still recorded
