"""Audit trail (F3): make every runset self-sufficient and fully reconstructable.

- ``snapshot_runset`` (called by the loop at ``runset_start``) archives the task YAML
  verbatim plus ``run_meta.json`` next to the journal.
- ``collect_audit`` normalizes a runset into a reconstruction document: meta, the task
  verbatim, the full timeline, a per-step view (attempts, observation, judgments with
  confidence, execution route/refusal, write rung, verification string, selection),
  approvals joined from the store, costs, and artifact hashes.
- ``export_bundle`` writes ``audit.json`` + ``REPORT.md`` + copies of the runset files to
  a bundle folder; ``render_report`` narrates the audit in markdown.

Old runsets without a snapshot, or approval ids missing from the store, degrade to
explicit warnings — never silent gaps.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

STEP_KINDS = {
    "step_attempt",
    "observation",
    "judgment",
    "action",
    "write_rung",
    "state_sig",
    "step_end",
    "step_start",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_journal(runset_dir: Path) -> list[dict]:
    path = runset_dir / "journal.jsonl"
    events: list[dict] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------- M1: snapshot ----------------


def snapshot_runset(
    runset_dir: Path,
    *,
    task: Any,
    task_path: Path | None = None,
    agent_id: str = "default",
    runs: int = 1,
    demo: bool = False,
    isolated: bool = False,
    keep_app: bool = False,
    policy: Any = None,
) -> None:
    """Archive the task (verbatim when possible) + run context next to the journal."""
    target = runset_dir / "task.yaml"
    source = ""
    if task_path is not None:
        try:
            target.write_text(Path(task_path).read_text(encoding="utf-8"), encoding="utf-8")
            source = f"file:{task_path}"
        except OSError:
            source = ""
    if not source:
        import yaml

        dump = task.model_dump() if hasattr(task, "model_dump") else {"task": str(task)}
        target.write_text(yaml.safe_dump(dump, allow_unicode=True, sort_keys=False), encoding="utf-8")
        source = "model"
    meta = {
        "task": getattr(task, "name", None) or "unknown",
        "task_source": source,
        "task_path": str(task_path) if task_path else None,
        "agent_id": agent_id,
        "runs": runs,
        "demo": demo,
        "isolated": isolated,
        "keep_app": keep_app,
        "policy_allow": sorted(getattr(policy, "allowed", []) or []) if policy is not None else None,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (runset_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ---------------- M2: collect + export ----------------


def _approval_rows(runset_dir: Path, event_ids: list[str]) -> tuple[list[dict], list[str]]:
    from eeze_agent.core.approvals import ApprovalStore

    rows: list[dict] = []
    warnings: list[str] = []
    store = ApprovalStore()
    for approval_id in event_ids:
        row = store.get(approval_id)
        if row is None:
            warnings.append(f"approval {approval_id} referenced in the journal but missing from the store")
            continue
        rows.append(
            {
                "id": row.get("id"),
                "step_id": row.get("step_id"),
                "risk_class": row.get("risk_class"),
                "status": row.get("status"),
                "decision": row.get("decision"),
                "decided_by": row.get("decided_by"),
                "decided_at": row.get("decided_at"),
                "reason": row.get("reason"),
            }
        )
    return rows, warnings


def collect_audit(runset_dir: Path) -> dict:
    """Normalize a runset into a reconstruction document."""
    journal = read_journal(runset_dir)
    if not journal:
        raise FileNotFoundError(f"no journal in {runset_dir}")

    warnings: list[str] = []
    meta = _load_json(runset_dir / "run_meta.json")
    if not meta:
        warnings.append("no run_meta.json snapshot — this run predates F3 (task source may have drifted)")
    task_text = ""
    task_file = runset_dir / "task.yaml"
    if task_file.exists():
        task_text = task_file.read_text(encoding="utf-8")
    else:
        fallback = meta.get("task_path")
        if fallback and Path(fallback).exists():
            task_text = Path(fallback).read_text(encoding="utf-8")
            warnings.append(f"no task.yaml snapshot in the runset — using the live file {fallback} (may differ)")
        else:
            warnings.append("no task snapshot available — steps below are from the journal only")
    summary = _load_json(runset_dir / "summary.json")

    steps: list[dict] = []
    index: dict[tuple, dict] = {}

    def step_entry(event: dict) -> dict:
        key = (event.get("run_index"), event.get("step_id"))
        entry = index.get(key)
        if entry is None:
            entry = {
                "run_index": key[0],
                "step_id": key[1],
                "attempts": 0,
                "observations": [],
                "judgments": [],
                "executions": [],
                "state_sigs": [],
                "ok": None,
                "ms": None,
                "selected": None,
                "write_method": None,
                "verify": None,
            }
            index[key] = entry
            steps.append(entry)
        return entry

    approval_ids: list[str] = []
    runset_events: list[dict] = []
    for event in journal:
        kind = event.get("kind")
        if kind in STEP_KINDS and event.get("step_id"):
            entry = step_entry(event)
            if kind in {"step_attempt", "step_start"}:
                entry["attempts"] = max(int(entry["attempts"]), int(event.get("attempt") or 1))
            elif kind == "observation":
                entry["observations"].append(
                    {
                        "window": event.get("window"),
                        "elements": event.get("elements"),
                        "degraded": event.get("degraded"),
                        "ms": event.get("ms"),
                    }
                )
            elif kind == "judgment":
                entry["judgments"].append(
                    {
                        "kind": event.get("judgment_kind"),
                        "question": event.get("question"),
                        "answer": event.get("answer"),
                        "confidence": event.get("confidence"),
                        "model": event.get("model"),
                        "ms": event.get("ms"),
                        "tokens": event.get("tokens"),
                    }
                )
            elif kind in {"action", "write_rung"}:
                entry["executions"].append(
                    {
                        "kind": kind,
                        "tool": event.get("tool"),
                        "rung": event.get("rung"),
                        "route": event.get("route"),
                        "effect": event.get("effect"),
                        "refusal": event.get("refusal"),
                        "status": event.get("status"),
                        "ms": event.get("ms"),
                    }
                )
            elif kind == "state_sig":
                entry["state_sigs"].append(
                    {"pre": event.get("pre"), "post": event.get("post"), "run_index": event.get("run_index")}
                )
            elif kind == "step_end":
                entry["ok"] = event.get("ok")
                entry["ms"] = event.get("ms")
                entry["selected"] = event.get("selected")
                entry["write_method"] = event.get("write_method")
                entry["verify"] = event.get("verify")
        else:
            runset_events.append(event)
            if kind == "runset_paused" and event.get("approval_id"):
                approval_ids.append(str(event["approval_id"]))

    for approval_id in summary.get("approval_id") or []:
        approval_ids.append(str(approval_id))
    if isinstance(summary.get("approval_id"), str):
        approval_ids.append(str(summary["approval_id"]))

    approvals, approval_warnings = _approval_rows(runset_dir, sorted(set(approval_ids)))
    warnings.extend(approval_warnings)

    artifacts: list[dict] = []
    for path in sorted(runset_dir.rglob("*")):
        if not path.is_file() or path.name == "journal.jsonl":
            continue
        try:
            artifacts.append(
                {
                    "path": str(path.relative_to(runset_dir)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        except OSError:
            continue

    return {
        "runset_id": runset_dir.name,
        "meta": meta,
        "task": task_text,
        "summary": summary,
        "steps": steps,
        "runset_events": runset_events,
        "approvals": approvals,
        "artifacts": artifacts,
        "integrity": {
            "journal_sha256": sha256_file(runset_dir / "journal.jsonl"),
            "journal_events": len(journal),
        },
        "warnings": warnings,
    }


def render_report(audit: dict) -> str:
    meta = audit.get("meta") or {}
    summary = audit.get("summary") or {}
    lines = [
        f"# Audit — {audit['runset_id']}",
        "",
        f"- task: **{meta.get('task') or summary.get('task') or 'unknown'}** ({meta.get('task_source', 'no snapshot')})",
        f"- agent: {meta.get('agent_id', '?')} · runs: {meta.get('runs', '?')} · demo: {meta.get('demo', '?')}",
        (
            f"- status: {summary.get('status', '?')} · success: {summary.get('success_rate', '?')}"
            f" · cost: {summary.get('cost_estimate_usd', 'n/a')}"
        ),
        (
            f"- integrity: journal sha256 `{audit['integrity']['journal_sha256'][:16]}…`"
            f" ({audit['integrity']['journal_events']} events)"
        ),
        "",
    ]
    if audit.get("warnings"):
        lines += ["## Warnings", ""]
        lines += [f"- {w}" for w in audit["warnings"]]
        lines.append("")
    lines += ["## Task (verbatim)", "", "```yaml", (audit.get("task") or "").rstrip(), "```", ""]
    lines += ["## Steps", ""]
    for step in audit["steps"]:
        lines.append(f"### run {step['run_index']} · `{step['step_id']}` — {'ok' if step['ok'] else 'failed' if step['ok'] is not None else '?'}")
        lines.append("")
        lines.append(f"- attempts: {step['attempts']} · {step['ms'] if step['ms'] is not None else '?'} ms")
        if step["selected"]:
            lines.append(f"- selected: {step['selected']}")
        if step["write_method"]:
            lines.append(f"- write method: {step['write_method']}")
        for obs in step["observations"]:
            lines.append(
                f"- observation: window {obs['window']!r} · {obs['elements']} elements"
                + (f" · degraded={obs['degraded']}" if obs["degraded"] else "")
            )
        for judgment in step["judgments"]:
            lines.append(
                f"- judgment [{judgment['kind']}]: {judgment['question']!r} → "
                f"{judgment['answer']!r} (conf {judgment['confidence']}, {judgment['model']})"
            )
        for execution in step["executions"]:
            detail = execution["tool"] or execution["rung"] or execution["kind"]
            lines.append(
                f"- execution: {detail} · route {execution['route']} · effect {execution['effect']}"
                + (f" · refusal {execution['refusal']}" if execution["refusal"] else "")
            )
        if step["verify"]:
            lines.append(f"- verify: `{step['verify']}`")
        lines.append("")
    if audit.get("approvals"):
        lines += ["## Approvals", ""]
        for approval in audit["approvals"]:
            lines.append(
                f"- `{approval['id']}` ({approval['risk_class']}, step {approval['step_id']}): "
                f"**{approval['status']}**"
                + (f" by {approval['decided_by']} at {approval['decided_at']}" if approval.get("decided_at") else "")
            )
        lines.append("")
    count = len(audit.get("artifacts") or [])
    if count:
        lines += ["## Artifacts", ""]
        lines += [
            f"- `{a['path']}` ({a['bytes']} B, sha256 {a['sha256'][:12]}…)" for a in audit["artifacts"][:40]
        ]
        if count > 40:
            lines.append(f"- … {count - 40} more")
        lines.append("")
    return "\n".join(lines)


def export_bundle(runset_dir: Path, *, out_dir: Path | None = None) -> dict:
    """Write audit.json + REPORT.md + copies of the runset into an export folder."""
    bundle = out_dir or runset_dir.parent.parent / "audits" / f"export-{runset_dir.name}"
    bundle.mkdir(parents=True, exist_ok=True)
    audit = collect_audit(runset_dir)
    (bundle / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    report = render_report(audit)
    (bundle / "REPORT.md").write_text(report, encoding="utf-8")
    copies = bundle / "runset"
    copies.mkdir(exist_ok=True)
    for path in sorted(runset_dir.rglob("*")):
        if not path.is_file():
            continue
        target = copies / path.relative_to(runset_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    hashes = {
        "audit.json": sha256_file(bundle / "audit.json"),
        "REPORT.md": sha256_file(bundle / "REPORT.md"),
    }
    return {
        "bundle": str(bundle),
        "audit_json": str(bundle / "audit.json"),
        "report_md": str(bundle / "REPORT.md"),
        "copied": str(copies),
        "hashes": hashes,
        "warnings": audit["warnings"],
    }
