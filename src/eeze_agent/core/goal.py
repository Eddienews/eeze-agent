"""Goal execution (F2 / M2): NL goal → plan → gated run-set, with bounded replanning.

The plan is persisted next to the run artifacts (``plan-task.yaml``), so a run that
pauses at the risk gate can be resumed later with the normal
``eeze run --resume <approval_id>`` path — the planned task is a first-class task.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from eeze_agent.agents.models import AgentContext
from eeze_agent.brains.planner import PlanError, Planner
from eeze_agent.core.journal import RunJournal
from eeze_agent.core.loop import run_set
from eeze_agent.core.models import StepSpec, TaskSpec

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 32) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (slug or "goal")[:max_len].rstrip("-")


def plan_to_task(plan: dict, name: str) -> TaskSpec:
    """Validate a planner plan into a TaskSpec (raises PlanError on garbage)."""
    app = plan.get("app")
    steps_raw = plan.get("steps")
    if not isinstance(app, str) or not app.strip():
        raise PlanError(f"plan has no app: {plan!r}")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise PlanError("plan has no steps")
    steps: list[StepSpec] = []
    for index, raw in enumerate(steps_raw, start=1):
        if not isinstance(raw, dict):
            raise PlanError(f"step {index} is not an object")
        data = dict(raw)
        data.setdefault("id", f"s{index}")
        try:
            steps.append(StepSpec(**data))
        except Exception as exc:  # pydantic validation / literal action
            raise PlanError(f"step {index} invalid: {exc}") from exc
    return TaskSpec(name=name, app=app.strip(), steps=steps)


def _failure_digest(summary: dict) -> str:
    parts = [
        f"status={summary.get('status')}",
        f"success={summary.get('success_rate')}",
        f"interference_runs={summary.get('interference_runs')}",
        f"external_input_events={summary.get('external_input_events')}",
    ]
    return "; ".join(str(p) for p in parts)


def execute_goal(
    goal: str,
    *,
    runs_root: Path,
    driver,
    brain,
    planner: Planner,
    agent_ctx: AgentContext,
    policy=None,
    approvals=None,
    runs: int = 1,
    demo: bool = False,
    max_replans: int = 2,
    brain_factory=None,
) -> dict:
    """Plan and execute ``goal``; replan (bounded) when a run fails.

    Returns an aggregate dict:
    ``{status: done|failed|needs_approval, goal, attempts, replans, runset_id,
       approval_id?, plan, runs_summary?}``

    ``brain_factory`` (optional) rebuilds the brain for router escalation between runs.
    """
    base_id = time.strftime("%Y%m%d-%H%M%S") + f"-goal-{slugify(goal)}"
    plan: dict | None = None
    history: list[dict] = []
    attempts = 0
    replans = 0
    failure_note = ""

    while True:
        attempts += 1
        runset_id = base_id if attempts == 1 else f"{base_id}-r{attempts}"
        out_dir = runs_root / runset_id
        out_dir.mkdir(parents=True, exist_ok=True)
        journal = RunJournal(runs_root, runset_id, agent_id=agent_ctx.agent_id)
        try:
            if plan is None:
                journal.event("goal", goal=goal, attempt=attempts)
                plan = planner.plan(goal)
            else:
                journal.event("goal", goal=goal, attempt=attempts,
                              replanned_from=failure_note or history[-1]["runset_id"])
            journal.event("plan", plan=plan)
            task = plan_to_task(plan, name=slugify(goal))
            task_file = out_dir / "plan-task.yaml"
            import yaml

            task_file.write_text(
                yaml.safe_dump(task.model_dump(), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

            summary = run_set(
                task=task,
                agent_ctx=agent_ctx,
                driver=driver,
                brain=brain,
                brain_factory=brain_factory,
                journal=journal,
                runs=runs,
                out_dir=out_dir,
                demo=demo,
                policy=policy,
                approvals=approvals,
                task_path=task_file,
            )
            (out_dir / "summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
        except PlanError as exc:
            summary = {"status": "plan_error", "error": str(exc), "success_rate": "0/0"}
            journal.event("plan_error", error=str(exc))
        finally:
            journal.close()

        history.append({"attempt": attempts, "runset_id": runset_id,
                        "status": summary.get("status"),
                        "success_rate": summary.get("success_rate")})

        if summary.get("status") == "needs_approval":
            return {
                "status": "needs_approval",
                "goal": goal,
                "attempts": attempts,
                "replans": replans,
                "runset_id": runset_id,
                "approval_id": summary.get("approval_id"),
                "plan": plan,
                "runs_summary": summary,
                "history": history,
            }

        ok_runs, eligible = (int(x) for x in str(summary.get("success_rate", "0/0")).split("/"))
        if eligible and ok_runs == eligible and summary.get("status") == "done":
            return {
                "status": "done",
                "goal": goal,
                "attempts": attempts,
                "replans": replans,
                "runset_id": runset_id,
                "plan": plan,
                "runs_summary": summary,
                "history": history,
            }

        if replans >= max_replans:
            return {
                "status": "failed",
                "goal": goal,
                "attempts": attempts,
                "replans": replans,
                "runset_id": runset_id,
                "plan": plan,
                "runs_summary": summary,
                "history": history,
            }

        failure_note = (
            f"attempt {attempts} ({runset_id}): {_failure_digest(summary)} "
            f"error={summary.get('error') or summary.get('paused_at') or 'run failed'}"
        )
        replans += 1
        try:
            plan = planner.replan(goal, plan, failure_note)
        except PlanError as exc:
            return {
                "status": "failed",
                "goal": goal,
                "attempts": attempts,
                "replans": replans,
                "runset_id": runset_id,
                "plan": plan,
                "error": f"replan failed: {exc}",
                "history": history,
            }
