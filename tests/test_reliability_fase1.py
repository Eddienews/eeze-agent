"""Fase 1 — loop/mission reliability fixes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from eeze_agent.core import risk as risk_mod
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.loop import _rendered_for_gate, render, retry_backoff_s
from eeze_agent.core.models import StepSpec, TaskSpec
from eeze_agent.core.routines import RoutineStore, path_safe, routine_log_path


# ---- render ------------------------------------------------------------------------------

def test_render_fills_known_and_keeps_unknown_placeholders():
    vars = {"run_dir": "C:/runs/1", "spec": "a.yaml"}
    out = render('ffmpeg -vf "drawtext=text={title}" -o "{run_dir}/out.mp4"', vars)
    assert out == 'ffmpeg -vf "drawtext=text={title}" -o "C:/runs/1/out.mp4"'


def test_render_survives_stray_braces():
    vars = {"run_dir": "D:/r"}
    out = render("powershell -c \"Get-Item x | % { $_.Length }\" > {run_dir}/n.txt", vars)
    assert out.endswith("> D:/r/n.txt")
    assert "{ $_.Length }" in out


def test_render_keeps_escaped_braces_semantics():
    assert render("{{literal}} {a}", {"a": "1"}) == "{literal} 1"


# ---- step ids / bounds -------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["x/../../evil", "..\\up", "has space", "", "a" * 200])
def test_step_id_cannot_escape_the_run_dir(bad: str):
    with pytest.raises(ValidationError):
        StepSpec(id=bad, action="check")


def test_step_bounds():
    with pytest.raises(ValidationError):
        StepSpec(id="s", action="run_script", command="x", retries=50)
    with pytest.raises(ValidationError):
        StepSpec(id="s", action="run_script", command="x", timeout_s=0)
    assert StepSpec(id="render-card.v2", action="check").id == "render-card.v2"


# ---- risk is judged on the rendered command ----------------------------------------------

def test_gate_classifies_the_rendered_command():
    task = TaskSpec(name="t", vars={"tool": "del /q C:\\Users\\me\\Documents\\*"},
                    steps=[StepSpec(id="s", action="run_script", command="{tool}")])
    step = task.steps[0]
    raw = risk_mod.classify_step(step, task).risk_class
    rendered = risk_mod.classify_step(_rendered_for_gate(step, dict(task.vars)), task).risk_class
    assert raw == "install_exec"
    assert risk_mod.RISK_ORDER.index(rendered) > risk_mod.RISK_ORDER.index(raw)


# ---- retries -----------------------------------------------------------------------------

def test_retry_backoff_grows_and_caps(monkeypatch):
    monkeypatch.setenv("EEZE_RETRY_BACKOFF_S", "1")
    assert [retry_backoff_s(n) for n in (1, 2, 3, 4, 5)] == [1, 2, 4, 8, 8]
    monkeypatch.setenv("EEZE_RETRY_BACKOFF_S", "0")
    assert retry_backoff_s(3) == 0


def test_timed_out_script_is_not_retried(tmp_path: Path):
    from eeze_agent.agents.models import Agent, AgentContext
    from eeze_agent.core import loop
    from eeze_agent.core.journal import RunJournal

    calls: list[int] = []

    def fake_script_step(**_kw):
        calls.append(1)
        raise loop.StepError("command timed out", detail={"timed_out": True})

    step = StepSpec(id="slow", action="run_script", command="sleep 999", retries=2)
    task = TaskSpec(name="t", steps=[step])
    journal = RunJournal(tmp_path, "rs", agent_id="default")
    orig = loop._run_script_step
    loop._run_script_step = fake_script_step
    try:
        result = loop.execute_step(
            task=task, step=step, ctx=AgentContext(agent=Agent(id="default", name="D")),
            driver=None, brain=None, journal=journal, state=loop.RunState(), run_ix=1,
            vars={}, demo=False,
        )
    finally:
        loop._run_script_step = orig
        journal.close()
    assert not result.ok
    assert calls == [1]


# ---- routine ids in paths ----------------------------------------------------------------

def test_mission_routine_ids_are_path_safe(tmp_path: Path):
    assert path_safe("mission:m1") == "mission-m1"
    assert routine_log_path(tmp_path, "mission:m1").name == "run-mission-m1.log"


# ---- deny closes the parked routine run --------------------------------------------------

def test_deny_closes_parked_routine_run(tmp_path: Path):
    db = tmp_path / "e.db"
    routines = RoutineStore(db)
    approvals = ApprovalStore(db)
    routines.add("r", name="R", kind="invoices", schedule={"type": "daily", "at": "08:00"})
    approval_id = approvals.request(
        runset_id="rs", task="routine:r", task_path="", agent_id="default", run_index=1,
        step_id="email-summary", step_index=0, action="email_summary",
        risk_class="external_send", reason="r", action_digest="d" * 64,
        run_state=lambda aid: {"approval_id": aid},
    )
    run_id = routines.start_run("r")
    routines.end_run(run_id, "r", status="needs_approval", approval_id=approval_id)
    approvals.decide(approval_id, "deny")
    assert routines.runs("r")[0]["status"] == "denied"
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT status FROM run_states").fetchone()[0] == "denied"


# ---- missions ----------------------------------------------------------------------------

def test_mission_spec_is_content_addressed(tmp_path: Path, monkeypatch):
    import yaml

    from eeze_agent.core import missions

    monkeypatch.setattr(missions, "_spec_for", lambda kind, path: type("S", (), {"output": ""})())
    monkeypatch.setattr(missions, "_eeze_exe", lambda: "eeze")
    mission = {"id": "m1", "kind": "3d", "plan": "a: 1\n", "name": "M"}
    t1 = missions.materialize(mission, home=tmp_path)
    v1 = yaml.safe_load(t1.read_text(encoding="utf-8"))["vars"]
    mission["plan"] = "a: 2\n"
    t2 = missions.materialize(mission, home=tmp_path)
    v2 = yaml.safe_load(t2.read_text(encoding="utf-8"))["vars"]
    assert v1["spec"] != v2["spec"] and v1["spec_sha256"] != v2["spec_sha256"]
    assert Path(v1["spec"]).read_text(encoding="utf-8") == "a: 1\n"  # the approved plan is intact
    assert (t2.parent / "spec.yaml").read_text(encoding="utf-8") == "a: 2\n"


def test_failed_mission_run_is_not_recorded_as_done(tmp_path: Path, monkeypatch):
    from eeze_agent.core import missions

    monkeypatch.setenv("EEZE_DB", str(tmp_path / "e.db"))
    store = missions.MissionStore(tmp_path)
    monkeypatch.setattr(missions, "materialize", lambda m, home=None: tmp_path / "task.yaml")
    (tmp_path / "task.yaml").write_text("x", encoding="utf-8")
    monkeypatch.setattr("eeze_agent.core.tasks.load_task",
                        lambda p: TaskSpec(name="t", steps=[StepSpec(id="s", action="check")]))
    monkeypatch.setattr("eeze_agent.core.loop.run_set", lambda **kw: {
        "status": "done", "success_rate": "0/1", "success_rate_all_runs": "0/1"})
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agents.yaml").write_text("agents:\n  - id: default\n    name: Default\n", encoding="utf-8")
    store_get = store.get
    monkeypatch.setattr(missions.MissionStore, "get",
                        lambda self, mid: {"id": mid, "kind": "task", "plan": "x", "agent_id": "default"})
    recorded: dict = {}
    monkeypatch.setattr(missions.MissionStore, "record_run",
                        lambda self, mid, **kw: recorded.update(kw))
    out = missions.run_mission("m1", repo_root=repo, home=tmp_path, brain=object())
    assert out["status"] == "error"
    assert recorded["status"] == "error"
    assert store_get  # keep reference (store constructed for side-effects)
