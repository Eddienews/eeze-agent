"""F2/M2 — planner plumbing: plan validation, gated goal execution, bounded replanning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_approvals import FakeDriver  # tests/ is on sys.path under pytest's rootdir mode

from eeze_agent.agents.models import AgentContext
from eeze_agent.agents.registry import DEFAULT_AGENT
from eeze_agent.brains.planner import PlanError
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.goal import execute_goal, plan_to_task, slugify
from eeze_agent.core.risk import Policy


class FakePlanner:
    def __init__(self, plans: list) -> None:
        self.plans = list(plans)
        self.calls: list[tuple] = []

    def plan(self, goal: str) -> dict:
        self.calls.append(("plan", goal))
        item = self.plans.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def replan(self, goal: str, previous: dict, failure: str) -> dict:
        self.calls.append(("replan", failure[:60]))
        item = self.plans.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


PLAN_OK = {
    "app": "Fake",
    "steps": [{"id": "ok", "action": "check"}],
}
PLAN_GATED = {
    "app": "Fake",
    "steps": [
        {"id": "a", "action": "check"},
        {"id": "install-x", "action": "invoke_menu", "menu": ["Tools", "Install X"]},
    ],
}
PLAN_BOOM = {
    "app": "Fake",
    "steps": [{"id": "boom", "action": "invoke_menu", "menu": ["File", "Boom"], "retries": 0}],
}


class BoomDriver(FakeDriver):
    def invoke_menu(self, ctx, pid, wid, path):
        if "-".join(path) == "File-Boom":
            raise RuntimeError("boom element not found")
        return super().invoke_menu(ctx, pid, wid, path)


def _goal(tmp_path: Path, planner: FakePlanner, **kw) -> dict:
    return execute_goal(
        kw.pop("goal", "do the fake thing"),
        runs_root=tmp_path / "runs",
        driver=kw.pop("driver", FakeDriver()),
        brain=None,
        planner=planner,  # type: ignore[arg-type]
        agent_ctx=AgentContext(agent=DEFAULT_AGENT),
        policy=Policy(),
        approvals=kw.pop("store", ApprovalStore(tmp_path / "eeze.db")),
        **kw,
    )


def test_slugify_and_plan_validation():
    assert slugify("Write a note!! With  Gmail") == "write-a-note-with-gmail"
    task = plan_to_task(PLAN_OK, "t")
    assert task.app == "Fake" and task.steps[0].id == "ok"
    with pytest.raises(PlanError):
        plan_to_task({"steps": []}, "t")
    with pytest.raises(PlanError):
        plan_to_task({"app": "Fake", "steps": []}, "t")
    with pytest.raises(PlanError):
        plan_to_task({"app": "Fake", "steps": [{"action": "teleport"}]}, "t")
    with pytest.raises(PlanError):
        plan_to_task({"app": "Fake", "steps": ["not-an-object"]}, "t")


def test_goal_pauses_at_gate_and_persists_plan_task(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    result = _goal(tmp_path, FakePlanner([PLAN_GATED]), store=store)
    assert result["status"] == "needs_approval"
    assert result["approval_id"]
    runset_id = result["runset_id"]
    task_file = tmp_path / "runs" / runset_id / "plan-task.yaml"
    assert task_file.exists()  # planned task persisted -> resumable like any task
    plan = json.loads((tmp_path / "runs" / runset_id / "journal.jsonl").read_text(encoding="utf-8").splitlines()[1])
    assert plan["kind"] == "plan" and plan["plan"]["app"] == "Fake"
    assert store.list("pending")[0]["task"] == "do-the-fake-thing"


def test_goal_replans_after_failure(tmp_path: Path):
    planner = FakePlanner([PLAN_BOOM, PLAN_OK])
    result = _goal(tmp_path, planner, driver=BoomDriver())
    assert result["status"] == "done"
    assert result["replans"] == 1
    assert [c[0] for c in planner.calls] == ["plan", "replan"]
    first = (tmp_path / "runs" / result["runset_id"].replace("-r2", "") / "journal.jsonl")
    events = [json.loads(line) for line in first.read_text(encoding="utf-8").splitlines()]
    assert any(e["kind"] == "runset_end" for e in events)
    second = tmp_path / "runs" / f"{result['runset_id']}" / "journal.jsonl"
    events2 = [json.loads(line) for line in second.read_text(encoding="utf-8").splitlines()]
    goal_events = [e for e in events2 if e["kind"] == "goal"]
    assert goal_events and goal_events[0]["attempt"] == 2 and goal_events[0].get("replanned_from")


def test_goal_gives_up_after_max_replans(tmp_path: Path):
    planner = FakePlanner([PLAN_BOOM, PLAN_BOOM])
    result = _goal(tmp_path, planner, driver=BoomDriver(), max_replans=1)
    assert result["status"] == "failed"
    assert result["replans"] == 1
    assert len(planner.calls) == 2


def test_goal_survives_plan_error_and_recovers(tmp_path: Path):
    planner = FakePlanner([PlanError("model returned prose"), PLAN_OK])
    result = _goal(tmp_path, planner)
    assert result["status"] == "done"
    assert result["replans"] == 1
    events = (tmp_path / "runs" / result["runset_id"].replace("-r2", "") / "journal.jsonl")
    kinds = [json.loads(x)["kind"] for x in events.read_text(encoding="utf-8").splitlines()]
    assert "plan_error" in kinds
