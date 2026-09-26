"""Replay (F3/M3): re-execute an archived task through the gated loop and diff outcomes.

A replay runs the **task snapshot** (or the recorded task path, with a warning) through
the normal loop with a fresh brain — recorded judgments are never replayed, so the diff
is an honest reproduction test, not a puppet show. The verdict lands in
``replay.json`` inside the replay runset: per-step match/divergence on ok, selected
element, and attempts, with both verification strings side by side.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from eeze_agent.agents.models import AgentContext
from eeze_agent.agents.registry import load_registry
from eeze_agent.brains.registry import make_brain
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.audit import collect_audit
from eeze_agent.core.journal import RunJournal
from eeze_agent.core.loop import run_set
from eeze_agent.core.risk import RISK_ORDER, Policy, policy_for_agent
from eeze_agent.core.tasks import load_task
from eeze_agent.drivers.cua import CuaDriver


def load_replay_task(runset_dir: Path):
    """Task from the snapshot (preferred) or the recorded live path (with a warning)."""
    snapshot = runset_dir / "task.yaml"
    if snapshot.exists():
        return load_task(snapshot), "snapshot"
    meta_file = runset_dir / "run_meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    task_path = meta.get("task_path")
    if task_path and Path(task_path).exists():
        return load_task(Path(task_path)), f"live-file:{task_path} (may differ from the original)"
    raise FileNotFoundError("no task snapshot and no usable task_path — cannot replay")


def diff_steps(original: list[dict], replay: list[dict]) -> dict:
    """Per-step comparison keyed by (run_index, step_id)."""
    def key(step: dict) -> tuple:
        return (step.get("run_index"), str(step.get("step_id")))

    orig_map = {key(s): s for s in original}
    replay_keys = set()
    rows: list[dict] = []
    matched = 0
    for step in replay:
        k = key(step)
        replay_keys.add(k)
        counterpart = orig_map.get(k)
        if counterpart is None:
            rows.append(
                {
                    "run_index": k[0],
                    "step_id": k[1],
                    "status": "new",
                    "detail": "step has no counterpart in the original run",
                }
            )
            continue
        checks = {
            "ok": counterpart.get("ok") == step.get("ok"),
            "selected": (counterpart.get("selected") or None) == (step.get("selected") or None),
            "attempts": int(counterpart.get("attempts") or 0) == int(step.get("attempts") or 0),
        }
        match = all(checks.values())
        matched += 1 if match else 0
        rows.append(
            {
                "run_index": k[0],
                "step_id": k[1],
                "status": "match" if match else "diverge",
                "checks": checks,
                "ok": {"original": counterpart.get("ok"), "replay": step.get("ok")},
                "selected": {"original": counterpart.get("selected"), "replay": step.get("selected")},
                "attempts": {"original": counterpart.get("attempts"), "replay": step.get("attempts")},
                "ms": {"original": counterpart.get("ms"), "replay": step.get("ms")},
                "verify": {"original": counterpart.get("verify"), "replay": step.get("verify")},
            }
        )
    missing = [{"run_index": k[0], "step_id": k[1]} for k in orig_map if k not in replay_keys]
    return {
        "rows": rows,
        "compared": len(replay),
        "matched": matched,
        "total_original": len(original),
        "missing_steps": missing,
        "all_match": bool(replay) and matched == len(replay) and not missing and len(replay) == len(original),
    }


def replay_runset(
    runset_id: str,
    *,
    repo_root: Path,
    runs: int | None = None,
    allow: list[str] | None = None,
    driver=None,
    brain=None,
) -> dict:
    runs_root = repo_root / "artifacts" / "runs"
    runset_dir = runs_root / runset_id
    if not runset_dir.exists():
        raise FileNotFoundError(f"unknown runset: {runset_id}")
    original = collect_audit(runset_dir)
    task, source = load_replay_task(runset_dir)
    meta = original.get("meta") or {}
    agent_id = meta.get("agent_id") or "default"
    registry = load_registry(repo_root)
    agent = registry.get(agent_id)

    policy = policy_for_agent(agent.permissions)
    extra = [str(x) for x in (allow or [])]
    unknown = [x for x in extra if x not in RISK_ORDER]
    if unknown:
        raise ValueError(f"unknown risk classes: {unknown}")
    if extra:
        policy = Policy(frozenset(policy.allowed | set(extra)))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    replay_id = f"{stamp}-replay-{runset_id}"
    out_dir = runs_root / replay_id
    journal = RunJournal(runs_root, replay_id, agent_id=agent_id)
    ctx = AgentContext(agent=agent)
    ctx.runset_id = replay_id
    summary = run_set(
        task=task,
        agent_ctx=ctx,
        driver=driver or CuaDriver(),
        brain=brain if brain is not None else make_brain(agent_id=agent_id, repo_root=repo_root, task=task),
        brain_factory=lambda **kw: make_brain(agent_id=agent_id, repo_root=repo_root, task=task, **kw),
        journal=journal,
        runs=int(runs if runs is not None else (meta.get("runs") or 1)),
        out_dir=out_dir,
        demo=bool(meta.get("demo")),
        keep_app=False,
        policy=policy,
        approvals=ApprovalStore(),
        task_path=(runset_dir / "task.yaml") if (runset_dir / "task.yaml").exists() else None,
    )
    journal.close()
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    replay_audit = collect_audit(out_dir)
    diff = diff_steps(original["steps"], replay_audit["steps"])
    verdict = {
        **diff,
        "original": runset_id,
        "replay": replay_id,
        "task_source": source,
        "task": getattr(task, "name", "unknown"),
        "original_status": original["summary"].get("status"),
        "replay_status": summary.get("status"),
        "replay_approval_id": summary.get("approval_id"),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / "replay.json").write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    return verdict
