"""run_script — the script/tool step layer (creative verticals): exec, risk floor, gate.

No GUI anywhere: a driver that raises on ANY attribute access is passed on purpose —
a script-only task must never touch the hands. Real commands are executed (cmd.exe
on Windows): file creation, non-zero exits, timeouts, gated pause → approve → resume.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from eeze_agent.agents.models import AgentContext
from eeze_agent.agents.registry import DEFAULT_AGENT
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.journal import RunJournal
from eeze_agent.core.loop import run_set
from eeze_agent.core.models import StepSpec, TaskSpec
from eeze_agent.core.risk import Policy, classify_step

ALLOW_EXEC = Policy(frozenset({"read", "write_local", "install_exec"}))
DEFAULT_POLICY = Policy()  # read + write_local only — exec must pause


class _NoDriver:
    """Any driver use by a script-only task is a bug: fail loudly."""

    def __getattr__(self, name: str):
        def _boom(*_a, **_k):
            raise AssertionError(f"driver.{name}() must not be called by a script-only task")

        return _boom


def _task(*steps: StepSpec, name: str = "script-task") -> TaskSpec:
    return TaskSpec(name=name, app="", steps=list(steps))


def _run(
    tmp_path: Path,
    runset_id: str,
    *,
    task: TaskSpec,
    policy: Policy,
    store: ApprovalStore | None = None,
    resume_state: dict | None = None,
) -> dict:
    journal = RunJournal(tmp_path / "runs", runset_id)
    summary = run_set(
        task=task,
        agent_ctx=AgentContext(agent=DEFAULT_AGENT),
        driver=_NoDriver(),
        brain=None,
        journal=journal,
        runs=1,
        out_dir=tmp_path / "out" / runset_id,
        policy=policy,
        approvals=store,
        task_path=tmp_path / f"{runset_id}.yaml",
        resume_state=resume_state,
    )
    journal.close()
    return summary


def _events(tmp_path: Path, runset_id: str) -> list[dict]:
    text = (tmp_path / "runs" / runset_id / "journal.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ---------------- execution ----------------


def test_script_step_runs_and_records_artifact_and_log(tmp_path: Path):
    task = _task(
        StepSpec(
            id="write",
            action="run_script",
            command="echo hello > out.txt",
            verify_code="file_exists|{run_dir}/out.txt",
        )
    )
    summary = _run(tmp_path, "rs-script-ok", task=task, policy=ALLOW_EXEC)
    assert summary["status"] == "done"
    assert summary["success_rate"] == "1/1"

    run_dir = tmp_path / "runs" / "rs-script-ok" / "run-01"
    assert (run_dir / "out.txt").exists()
    assert "hello" in (run_dir / "out.txt").read_text(encoding="utf-8")
    log = (run_dir / "step-write.log").read_text(encoding="utf-8")
    assert "$ echo hello > out.txt" in log
    assert "exit=0" in log

    events = _events(tmp_path, "rs-script-ok")
    assert any(e["kind"] == "no_app_task" for e in events)
    act = [e for e in events if e["kind"] == "action" and e.get("tool") == "run_script"]
    assert act and act[0]["status"] == "ok" and act[0]["effect"] == "exit=0"
    art = [e for e in events if e["kind"] == "script_artifacts"]
    assert art and "out.txt" in art[0]["files"]
    end = [e for e in events if e["kind"] == "step_end"][-1]
    assert end["ok"] is True and end["exit_code"] == "0"


def test_script_step_nonzero_exit_fails_the_step(tmp_path: Path):
    task = _task(StepSpec(id="boom", action="run_script", command="exit 3", retries=0))
    summary = _run(tmp_path, "rs-script-exit", task=task, policy=ALLOW_EXEC)
    assert summary["success_rate"] == "0/1"

    events = _events(tmp_path, "rs-script-exit")
    act = [e for e in events if e["kind"] == "action" and e.get("tool") == "run_script"]
    assert act and act[0]["status"] == "failed" and act[0]["effect"] == "exit=3"
    end = [e for e in events if e["kind"] == "step_end"][-1]
    assert end["ok"] is False
    assert "exited with code 3" in end["error"]


def test_script_step_timeout_is_killed_and_fails(tmp_path: Path):
    sleepy = f'"{sys.executable}" -c "import time; time.sleep(20)"'
    task = _task(
        StepSpec(id="slow", action="run_script", command=sleepy, timeout_s=1.0, retries=0)
    )
    summary = _run(tmp_path, "rs-script-timeout", task=task, policy=ALLOW_EXEC)
    assert summary["success_rate"] == "0/1"
    events = _events(tmp_path, "rs-script-timeout")
    end = [e for e in events if e["kind"] == "step_end"][-1]
    assert end["ok"] is False
    assert "timed out" in end["error"]
    assert end["timed_out"] == "True"


def test_script_task_needs_no_app_and_skips_jev(tmp_path: Path):
    task = _task(
        StepSpec(
            id="just-echo",
            action="run_script",
            command="echo ok",
            verify_jev="a file was written",
        )
    )
    summary = _run(tmp_path, "rs-script-noapp", task=task, policy=ALLOW_EXEC)
    assert summary["success_rate"] == "1/1"  # brain=None: a jev call would crash
    events = _events(tmp_path, "rs-script-noapp")
    skipped = [e for e in events if e["kind"] == "verify_jev_skipped"]
    assert skipped and skipped[0]["step_id"] == "just-echo"


def test_script_does_not_inherit_host_credentials(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_BRAIN_API_KEY", "synthetic-no-inheritance")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-provider-secret")
    command = (f'"{sys.executable}" -c "import os; '
               "print(os.getenv('EEZE_BRAIN_API_KEY', 'absent')); "
               "print(os.getenv('OPENAI_API_KEY', 'absent'))\"")
    task = _task(StepSpec(id="env", action="run_script", command=command))
    summary = _run(tmp_path, "rs-script-env", task=task, policy=ALLOW_EXEC)
    assert summary["status"] == "done"
    log = (tmp_path / "runs" / "rs-script-env" / "run-01" / "step-env.log").read_text(
        encoding="utf-8"
    )
    stdout = log.split("--- stdout ---", 1)[1].split("--- stderr ---", 1)[0]
    assert [line for line in stdout.splitlines() if line] == ["absent", "absent"]
    assert "synthetic-no-inheritance" not in log
    assert "synthetic-provider-secret" not in log
    assert os.getenv("EEZE_BRAIN_API_KEY") == "synthetic-no-inheritance"


def test_script_refuses_cwd_outside_run_before_creating_files(tmp_path: Path):
    outside = tmp_path / "outside"
    task = _task(StepSpec(id="escape", action="run_script", cwd=str(outside),
                          command="echo escaped > marker.txt", retries=0))
    summary = _run(tmp_path, "rs-script-escape", task=task, policy=ALLOW_EXEC)
    assert summary["success_rate"] == "0/1"
    assert not outside.exists()
    assert not (outside / "marker.txt").exists()
    events = _events(tmp_path, "rs-script-escape")
    assert any("outside the run directory" in str(e.get("error", "")) for e in events)


# ---------------- risk floor ----------------


def test_run_script_defaults_to_install_exec():
    step = StepSpec(id="x", action="run_script", command="echo hi")
    cls = classify_step(step, TaskSpec(name="t", app="", steps=[step]))
    assert cls.risk_class == "install_exec"


def test_script_command_heuristics_raise_the_class():
    for command in ("rm -rf /tmp/proj", "format c: /q", "diskpart", "git reset --hard"):
        step = StepSpec(id="x", action="run_script", command=command)
        cls = classify_step(step, TaskSpec(name="t", app="", steps=[step]))
        assert cls.risk_class == "destructive", command


# ---------------- gate: pause → approve → resume ----------------


def test_script_step_pauses_then_resume_runs_it(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    task = _task(
        StepSpec(
            id="make",
            action="run_script",
            command="echo gated > g.txt",
            retries=0,
            verify_code="file_exists|{run_dir}/g.txt",
        )
    )
    summary = _run(tmp_path, "rs-script-gate", task=task, policy=DEFAULT_POLICY, store=store)
    assert summary["status"] == "needs_approval"
    assert summary["paused_at"]["risk_class"] == "install_exec"
    assert not (tmp_path / "runs" / "rs-script-gate" / "run-01" / "g.txt").exists()

    pending = store.list("pending")
    assert len(pending) == 1
    approval_id = pending[0]["id"]
    payload = json.loads(pending[0]["payload"])
    assert payload.get("command") == "echo gated > g.txt"
    assert payload.get("run_dir", "").endswith("run-01")

    store.decide(approval_id, "approve", decided_by="tester")
    state_row = store.run_state_for(approval_id)
    assert state_row and state_row["status"] == "waiting"

    summary2 = _run(
        tmp_path, "rs-script-gate", task=task, policy=DEFAULT_POLICY, store=store,
        resume_state=json.loads(state_row["payload"]),
    )
    assert summary2["status"] == "done"
    assert summary2["success_rate"] == "1/1"
    assert (tmp_path / "runs" / "rs-script-gate" / "run-01" / "g.txt").exists()

    events = _events(tmp_path, "rs-script-gate")
    assert any(e["kind"] == "approval_requested" for e in events)
    assert any(e["kind"] == "runset_resume" for e in events)


def test_script_step_grant_allows_repeat_without_pause(tmp_path: Path):
    store = ApprovalStore(tmp_path / "eeze.db")
    store.grant(agent_id="default", risk_class="install_exec", scope="task", task="script-task")
    task = _task(StepSpec(id="quick", action="run_script", command="echo free > f.txt"))
    summary = _run(tmp_path, "rs-script-grant", task=task, policy=DEFAULT_POLICY, store=store)
    assert summary["status"] == "done"
    events = _events(tmp_path, "rs-script-grant")
    assert any(e["kind"] == "grant_hit" for e in events)
