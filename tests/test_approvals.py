"""F2/M1 — approval store + the gated loop (pause → decide → resume; grants)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eeze_agent.agents.models import AgentContext
from eeze_agent.agents.registry import DEFAULT_AGENT
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.journal import RunJournal
from eeze_agent.core.loop import run_set
from eeze_agent.core.models import ActionOutcome, Observation, StepSpec, TaskSpec
from eeze_agent.core.risk import Policy

# ---------------- fake driver (no GUI) ----------------


class FakeDriver:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def launch(self, ctx, *, name=None, aumid=None):
        self.calls.append(("launch", name or aumid))
        return {"pid": 101, "windows": [{"window_id": 9}]}

    def main_window(self, ctx, app):
        return {"pid": 101, "window_id": 9, "title": f"{app} - Untitled", "minimized": False}

    def list_windows(self, ctx):
        return []

    def kill(self, ctx, pid):
        self.calls.append(("kill", pid))

    def restore_window(self, ctx, pid, wid):
        return ActionOutcome(tool="restore", status="ok")

    def capture(self, ctx, pid, wid, screenshot=False):
        return Observation(pid=pid, window_id=wid, window_title="Fake - Untitled", elements=[])

    def invoke_menu(self, ctx, pid, wid, path):
        self.calls.append(("invoke_menu", "-".join(path)))
        return ActionOutcome(tool="invoke_menu", status="ok")

    def click(self, ctx, pid, wid, token=None, **kw):
        self.calls.append(("click", token))
        return ActionOutcome(tool="click", status="ok")

    def type_text(self, ctx, pid, wid, text):
        self.calls.append(("type_text", text))
        return ActionOutcome(tool="type_text", status="ok")

    def set_text(self, ctx, pid, wid, token, text):
        return ActionOutcome(tool="set_text", status="ok")

    def hotkey(self, ctx, pid, wid, keys):
        return ActionOutcome(tool="hotkey", status="ok")

    def drag(self, ctx, pid, wid, **kw):
        return ActionOutcome(tool="drag", status="ok")

    def press_key(self, ctx, pid, wid, key):
        return ActionOutcome(tool="press_key", status="ok")


def _task() -> TaskSpec:
    return TaskSpec(
        name="gate-demo",
        app="Fake",
        steps=[
            StepSpec(id="read-1", action="check"),
            StepSpec(id="install-1", action="invoke_menu", menu=["Tools", "Install sample addon"]),
            StepSpec(id="read-2", action="check"),
        ],
    )


def _run(tmp_path: Path, driver: FakeDriver, store: ApprovalStore, runset_id: str,
         resume_state: dict | None = None, task: TaskSpec | None = None,
         agent=DEFAULT_AGENT) -> dict:
    journal = RunJournal(tmp_path / "runs", runset_id)
    summary = run_set(
        task=task or _task(),
        agent_ctx=AgentContext(agent=agent),
        driver=driver,
        brain=None,
        journal=journal,
        runs=1,
        out_dir=tmp_path / "out" / runset_id,
        policy=Policy(),
        approvals=store,
        task_path=tmp_path / "task.yaml",
        resume_state=resume_state,
    )
    journal.close()
    return summary


def _journal_events(tmp_path: Path, runset_id: str) -> list[dict]:
    text = (tmp_path / "runs" / runset_id / "journal.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ---------------- store unit tests ----------------


def test_store_request_decide_and_counts(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    approval_id = store.request(
        runset_id="rs1", task="t", task_path="t.yaml", agent_id="default", run_index=1,
        step_id="s1", step_index=0, action="click", risk_class="install_exec", reason="why",
        payload={"action": "click"},
    )
    row = store.get(approval_id)
    assert row and row["status"] == "pending"
    assert store.count("pending") == 1
    decided = store.decide(approval_id, "approve", decided_by="tester")
    assert decided["status"] == "approved" and decided["decided_by"] == "tester"
    assert store.count("pending") == 0
    with pytest.raises(KeyError):
        store.decide(approval_id, "approve")


def test_store_deny_marks_run_state_denied(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    approval_id = store.request(
        runset_id="rs1", task="t", task_path="", agent_id="default", run_index=1,
        step_id="s1", step_index=0, action="click", risk_class="destructive", reason="why",
        payload={},
    )
    store.save_run_state(approval_id, {"x": 1})
    store.decide(approval_id, "deny")
    row = store.run_state_for(approval_id)
    assert row and row["status"] == "denied"


def test_store_grants_scope_ttl_revoke(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    gid = store.grant(agent_id="default", risk_class="install_exec", scope="task", task="my-task")
    assert store.active_grant("default", "install_exec", "my-task")
    assert not store.active_grant("default", "install_exec", "other-task")
    other = store.grant(agent_id="default", risk_class="system", scope="agent")
    assert store.active_grant("default", "system", "any-task")["id"] == other
    expired = store.grant(
        agent_id="default", risk_class="external_send", scope="agent", ttl_hours=-1
    )
    assert store.active_grant("default", "external_send", "any-task") is None
    assert expired  # created, but already expired
    assert store.revoke_grant(gid) and not store.active_grant("default", "install_exec", "my-task")


def test_store_run_state_superseded(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    approval_id = store.request(
        runset_id="rs1", task="t", task_path="", agent_id="default", run_index=1,
        step_id="s1", step_index=0, action="click", risk_class="install_exec", reason="",
        payload={},
    )
    first = store.save_run_state(approval_id, {"n": 1})
    store.save_run_state(approval_id, {"n": 2})
    latest = store.run_state_for(approval_id)
    assert latest and json.loads(latest["payload"])["n"] == 2
    # the superseded one is still on disk but not returned
    assert first != latest["id"]


def test_changed_approved_step_refuses_before_any_driver_call(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    summary = _run(tmp_path, FakeDriver(), store, "rs-change")
    approval_id = summary["approval_id"]
    store.decide(approval_id, "approve")
    state = json.loads(store.run_state_for(approval_id)["payload"])
    changed = _task()
    changed.steps[1].menu = ["Tools", "Install different addon"]
    driver = FakeDriver()
    with pytest.raises(ValueError, match="approval.*mismatch"):
        _run(tmp_path, driver, store, "rs-change", resume_state=state, task=changed)
    assert driver.calls == []


@pytest.mark.parametrize("mutation", ["command", "destination", "agent", "order", "risk", "vars"])
def test_approved_context_changes_never_dispatch(tmp_path: Path, mutation: str):
    store = ApprovalStore(tmp_path / "eeze.db")
    task = _task()
    task.name = "script-gate"
    task.steps[1] = StepSpec(id="script", action="run_script", command="echo {target}", cwd="{run_dir}")
    task.vars = {"target": "original"}
    summary = _run(tmp_path, FakeDriver(), store, "rs-binding", task=task)
    approval_id = summary["approval_id"]
    store.decide(approval_id, "approve")
    state = json.loads(store.run_state_for(approval_id)["payload"])
    candidate = task.model_copy(deep=True)
    agent = DEFAULT_AGENT
    if mutation == "command":
        candidate.steps[1].command = "echo changed"
    elif mutation == "destination":
        candidate.steps[1].cwd = "elsewhere"
    elif mutation == "agent":
        agent = DEFAULT_AGENT.model_copy(update={"id": "other"})
    elif mutation == "order":
        candidate.steps.reverse()
    elif mutation == "risk":
        candidate.steps[1].risk = "system"
    else:
        state["partial"]["vars"]["target"] = "changed"
    driver = FakeDriver()
    with pytest.raises(ValueError, match="approval identity mismatch"):
        _run(tmp_path, driver, store, "rs-binding", state, task=candidate, agent=agent)
    assert driver.calls == []
    assert store.run_state_for(approval_id)["status"] == "waiting"


def test_approved_resume_is_one_shot(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    approval_id = _run(tmp_path, FakeDriver(), store, "rs-once")["approval_id"]
    store.decide(approval_id, "approve")
    state = json.loads(store.run_state_for(approval_id)["payload"])
    first = FakeDriver()
    assert _run(tmp_path, first, store, "rs-once", state)["status"] == "done"
    assert sum(call[0] == "invoke_menu" for call in first.calls) == 1
    second = FakeDriver()
    with pytest.raises(ValueError, match="already consumed"):
        _run(tmp_path, second, store, "rs-once", state)
    assert second.calls == []


def test_legacy_approval_without_digest_fails_closed(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    approval_id = _run(tmp_path, FakeDriver(), store, "rs-legacy")["approval_id"]
    store.decide(approval_id, "approve")
    with store._connect() as con:
        con.execute("UPDATE approvals SET action_digest=NULL WHERE id=?", (approval_id,))
    state = json.loads(store.run_state_for(approval_id)["payload"])
    driver = FakeDriver()
    with pytest.raises(ValueError, match="approval identity mismatch"):
        _run(tmp_path, driver, store, "rs-legacy", state)
    assert driver.calls == []


@pytest.mark.parametrize("change", ["out_dir", "runs", "agent_permissions"])
def test_resume_rejects_changed_execution_scope(tmp_path: Path, change: str):
    store = ApprovalStore(tmp_path / "eeze.db")
    approval_id = _run(tmp_path, FakeDriver(), store, "rs-scope")["approval_id"]
    store.decide(approval_id, "approve")
    state = json.loads(store.run_state_for(approval_id)["payload"])
    driver = FakeDriver()
    agent = DEFAULT_AGENT
    if change == "agent_permissions":
        agent = DEFAULT_AGENT.model_copy(update={"permissions": {"danger": True}})
    journal = RunJournal(tmp_path / "runs", "rs-scope")
    with pytest.raises(ValueError, match="approval identity mismatch"):
        run_set(task=_task(), agent_ctx=AgentContext(agent=agent), driver=driver,
                brain=None, journal=journal, runs=2 if change == "runs" else 1,
                out_dir=tmp_path / "out" / ("other" if change == "out_dir" else "rs-scope"),
                task_path=tmp_path / "task.yaml",
                policy=Policy(), approvals=store, resume_state=state)
    assert driver.calls == []
    assert store.run_state_for(approval_id)["status"] == "waiting"


# ---------------- gated loop: pause → decide → resume ----------------


def test_gate_pauses_then_resume_completes(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    summary = _run(tmp_path, FakeDriver(), store, "rs-pause")
    assert summary["status"] == "needs_approval"
    assert summary["paused_at"]["risk_class"] == "install_exec"
    pending = store.list("pending")
    assert len(pending) == 1
    approval_id = pending[0]["id"]
    assert summary["approval_id"] == approval_id

    # approve + resume (fresh store instance = simulated process restart)
    store2 = ApprovalStore(tmp_path / "eeze.db")
    store2.decide(approval_id, "approve", decided_by="tester")
    state_row = store2.run_state_for(approval_id)
    assert state_row and state_row["status"] == "waiting"
    payload = json.loads(state_row["payload"])

    driver2 = FakeDriver()
    summary2 = _run(tmp_path, driver2, store2, "rs-pause", resume_state=payload)
    assert summary2["status"] == "done"
    assert summary2["success_rate"] == "1/1"
    assert ("invoke_menu", "Tools-Install sample addon") in driver2.calls
    events = _journal_events(tmp_path, "rs-pause")
    kinds = [e["kind"] for e in events]
    assert "approval_requested" in kinds and "runset_resume" in kinds


def test_denied_approval_blocks_resume(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    summary = _run(tmp_path, FakeDriver(), store, "rs-deny")
    approval_id = summary["approval_id"]
    assert approval_id
    store.decide(approval_id, "deny", decided_by="tester")
    row = store.run_state_for(approval_id)
    assert row is not None and row["status"] == "denied"
    # the driver must NOT have executed the gated step
    assert all(call[0] != "invoke_menu" for call in FakeDriver().calls)


def test_grant_allows_repeat_without_pause(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    _run(tmp_path, FakeDriver(), store, "rs-g1")  # pauses once
    store.grant(agent_id="default", risk_class="install_exec", scope="task", task="gate-demo")

    driver = FakeDriver()
    summary = _run(tmp_path, driver, store, "rs-g2")
    assert summary["status"] == "done"
    assert ("invoke_menu", "Tools-Install sample addon") in driver.calls
    events = _journal_events(tmp_path, "rs-g2")
    assert any(e["kind"] == "grant_hit" for e in events)


def test_revoked_grant_pauses_again(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    gid = store.grant(agent_id="default", risk_class="install_exec", scope="task", task="gate-demo")
    store.revoke_grant(gid)
    summary = _run(tmp_path, FakeDriver(), store, "rs-g3")
    assert summary["status"] == "needs_approval"


def test_ungated_run_unchanged(tmp_path: Path):
    """Without a policy the loop behaves exactly like F1 (no gate at all)."""
    store = ApprovalStore(tmp_path / "eeze.db")
    journal = RunJournal(tmp_path / "runs", "rs-plain")
    summary = run_set(
        task=_task(), agent_ctx=AgentContext(agent=DEFAULT_AGENT), driver=FakeDriver(),
        brain=None, journal=journal, runs=1, out_dir=tmp_path / "out" / "plain",
    )
    journal.close()
    assert summary["status"] == "done"
    assert store.count() == 0
