"""F3 — audit: snapshot, collect, export, render; replay diff + integration (stubbed loop)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.audit import (
    collect_audit,
    export_bundle,
    sha256_file,
    snapshot_runset,
)
from eeze_agent.core.replay import diff_steps, load_replay_task, replay_runset
from eeze_agent.core.risk import Policy

TASK_YAML = """\
name: f3-fixture
app: Notepad
aumid: Microsoft.WindowsNotepad_8wekyb3d8bbwe!App
steps:
  - id: set_content
    action: set_text
    intent: set the text
    text: "{token}"
  - id: install-helper
    action: click
    intent: click the File menu item
"""


def _seed_runset(repo: Path, runset="rs-orig", *, selected_helper="MenuItem 'File'") -> Path:
    rs = repo / "artifacts" / "runs" / runset
    rs.mkdir(parents=True, exist_ok=True)
    (rs / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (rs / "run_meta.json").write_text(
        json.dumps({"task": "f3-fixture", "task_source": "file:x", "task_path": None,
                    "agent_id": "default", "runs": 1, "demo": False, "isolated": False,
                    "keep_app": False, "policy_allow": ["read", "write_local"]}),
        encoding="utf-8",
    )
    events = [
        {"kind": "runset_start", "task": "f3-fixture", "agent_id": "default", "runs": 1},
        {"kind": "run_start", "run_index": 1},
        {"kind": "step_attempt", "run_index": 1, "step_id": "set_content", "attempt": 1},
        {"kind": "observation", "run_index": 1, "step_id": "set_content", "window": "* - Notepad",
         "elements": 31, "degraded": None, "ms": 900.0},
        {"kind": "judgment", "run_index": 1, "step_id": "set_content", "judgment_kind": "select_element",
         "question": "which is the editor?", "answer": "Document 'Text editor'", "confidence": 0.99,
         "model": "jev-1.13.0", "ms": 280.0, "tokens": 1200},
        {"kind": "write_rung", "run_index": 1, "step_id": "set_content", "rung": "set_value",
         "tool": "set_value", "route": "accessibility", "effect": "unverifiable"},
        {"kind": "step_end", "run_index": 1, "step_id": "set_content", "ok": True, "attempts": 1,
         "ms": 1200.0, "selected": "Document 'Text editor'", "write_method": "set_value",
         "verify": "code:doc_equals -> True"},
        {"kind": "step_attempt", "run_index": 1, "step_id": "install-helper", "attempt": 1},
        {"kind": "action", "run_index": 1, "step_id": "install-helper", "tool": "click",
         "route": "accessibility", "effect": "unverifiable"},
        {"kind": "step_end", "run_index": 1, "step_id": "install-helper", "ok": True, "attempts": 1,
         "ms": 2800.0, "selected": selected_helper, "write_method": None, "verify": None},
        {"kind": "run_end", "run_index": 1, "ok": True, "cycle_ms": 4000.0},
        {"kind": "runset_end", "status": "done", "success_rate": "1/1"},
    ]
    (rs / "journal.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    (rs / "summary.json").write_text(json.dumps({"status": "done", "success_rate": "1/1"}), encoding="utf-8")
    return rs


# ---------------- snapshot ----------------

def test_snapshot_verbatim_and_model_dump(tmp_path: Path):
    task_file = tmp_path / "t.yaml"
    task_file.write_text(TASK_YAML, encoding="utf-8")
    task = SimpleNamespace(name="f3-fixture")
    rs = tmp_path / "rs"
    rs.mkdir()
    snapshot_runset(rs, task=task, task_path=task_file, agent_id="default", runs=2,
                    policy=Policy(frozenset({"read", "write_local"})))
    assert (rs / "task.yaml").read_text(encoding="utf-8") == TASK_YAML  # verbatim
    meta = json.loads((rs / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["task_source"].startswith("file:") and meta["runs"] == 2
    assert meta["policy_allow"] == ["read", "write_local"]

    rs2 = tmp_path / "rs2"
    rs2.mkdir()

    class FakeTask:
        name = "generated"

        def model_dump(self):
            return {"name": "generated", "steps": [{"id": "s1"}]}

    snapshot_runset(rs2, task=FakeTask(), task_path=None)
    meta2 = json.loads((rs2 / "run_meta.json").read_text(encoding="utf-8"))
    assert meta2["task_source"] == "model"
    assert "generated" in (rs2 / "task.yaml").read_text(encoding="utf-8")


# ---------------- collect + warnings ----------------

def test_collect_audit_joins_approvals_and_warns(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    rs = _seed_runset(tmp_path / "repo")
    # add a pause event + a real approval row
    store = ApprovalStore()
    ap = store.request(runset_id="rs-orig", task="f3-fixture", task_path="", agent_id="default",
                       run_index=1, step_id="install-helper", step_index=1, action="click",
                       risk_class="install_exec", reason="declared", payload={})
    store.decide(ap, "approve")
    with (rs / "journal.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "runset_paused", "run_index": 1, "step_id": "install-helper",
                             "approval_id": ap}) + "\n")
        fh.write(json.dumps({"kind": "runset_resume"}) + "\n")

    audit = collect_audit(rs)
    assert len(audit["steps"]) == 2
    step = audit["steps"][0]
    assert step["ok"] is True and step["selected"] == "Document 'Text editor'"
    assert step["verify"] == "code:doc_equals -> True"
    assert step["judgments"][0]["confidence"] == 0.99
    assert step["executions"][0]["rung"] == "set_value"
    assert audit["approvals"][0]["id"] == ap and audit["approvals"][0]["status"] == "approved"
    assert not audit["warnings"]

    # ghost approval id degrades to a warning
    with (rs / "journal.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "runset_paused", "run_index": 1, "step_id": "x",
                             "approval_id": "ap-doesnotexist"}) + "\n")
    audit2 = collect_audit(rs)
    assert any("ap-doesnotexist" in w for w in audit2["warnings"])


def test_collect_audit_no_meta_warns(tmp_path: Path):
    rs = _seed_runset(tmp_path / "repo")
    (rs / "run_meta.json").unlink()
    audit = collect_audit(rs)
    assert any("predates F3" in w for w in audit["warnings"])
    assert len(audit["steps"]) == 2  # journal still reconstructs the steps


# ---------------- export + render ----------------

def test_export_bundle_and_report(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    rs = _seed_runset(tmp_path / "repo")
    # an artifact file to be copied + hashed
    run_dir = rs / "run-01"
    run_dir.mkdir(exist_ok=True)
    (run_dir / "step-set_content.png").write_bytes(b"\x89PNG fake")
    result = export_bundle(rs)
    bundle = Path(result["bundle"])
    assert (bundle / "audit.json").exists() and (bundle / "REPORT.md").exists()
    assert (bundle / "runset" / "task.yaml").exists()
    assert (bundle / "runset" / "run-01" / "step-set_content.png").exists()
    assert result["hashes"]["audit.json"] == sha256_file(bundle / "audit.json")
    audit = json.loads((bundle / "audit.json").read_text(encoding="utf-8"))
    assert audit["integrity"]["journal_sha256"] and audit["artifacts"][0]["sha256"]
    report = (bundle / "REPORT.md").read_text(encoding="utf-8")
    assert "## Steps" in report and "install-helper" in report and "code:doc_equals" in report


# ---------------- replay diff ----------------

def test_diff_steps_match_and_diverge():
    orig = [
        {"run_index": 1, "step_id": "a", "ok": True, "attempts": 1, "selected": "X", "ms": 100.0},
        {"run_index": 1, "step_id": "b", "ok": True, "attempts": 1, "selected": "Y", "ms": 200.0},
    ]
    same = [dict(s) for s in orig]
    diff = diff_steps(orig, same)
    assert diff["all_match"] and diff["matched"] == 2 and not diff["missing_steps"]

    changed = [dict(orig[0]), {**orig[1], "selected": "Z"}]
    diff2 = diff_steps(orig, changed)
    assert not diff2["all_match"]
    assert diff2["rows"][1]["status"] == "diverge" and diff2["rows"][1]["checks"]["selected"] is False

    diff3 = diff_steps(orig, [orig[0]])
    assert not diff3["all_match"] and diff3["missing_steps"] == [{"run_index": 1, "step_id": "b"}]


def test_replay_runset_with_stubbed_loop(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "agents.yaml", repo / "agents.yaml")
    _seed_runset(repo)

    import eeze_agent.core.replay as replay_mod

    def fake_run_set(**kw):
        journal = kw["journal"]
        journal.event("runset_start", task=kw["task"].name, agent_id="default", runs=kw["runs"])
        for step in kw["task"].steps:
            journal.event("step_attempt", run_index=1, step_id=step.id, attempt=1)
            selected = "Document 'Text editor'" if step.id == "set_content" else "MenuItem 'File'"
            journal.event("step_end", run_index=1, step_id=step.id, ok=True, attempts=1, ms=100.0,
                          selected=selected, write_method="set_value" if step.id == "set_content" else None,
                          verify="code:doc_equals -> True" if step.id == "set_content" else None)
        journal.event("run_end", run_index=1, ok=True, cycle_ms=200.0)
        journal.event("runset_end", status="done", success_rate="1/1")
        return {"status": "done", "success_rate": "1/1"}

    monkeypatch.setattr(replay_mod, "run_set", fake_run_set)
    task, source = load_replay_task(repo / "artifacts" / "runs" / "rs-orig")
    assert source == "snapshot" and task.name == "f3-fixture"

    verdict = replay_runset("rs-orig", repo_root=repo, driver=object(), brain=object())
    assert verdict["all_match"] is True and verdict["matched"] == 2
    assert verdict["replay_status"] == "done" and verdict["task_source"] == "snapshot"
    replay_file = repo / "artifacts" / "runs" / verdict["replay"] / "replay.json"
    assert replay_file.exists()
    assert json.loads(replay_file.read_text(encoding="utf-8"))["all_match"] is True

    # now make the original differ → divergence is reported
    rs = repo / "artifacts" / "runs" / "rs-orig"
    content = (rs / "journal.jsonl").read_text(encoding="utf-8").replace("MenuItem 'File'", "Button 'Zzz'")
    (rs / "journal.jsonl").write_text(content, encoding="utf-8")
    verdict2 = replay_runset("rs-orig", repo_root=repo, driver=object(), brain=object())
    assert verdict2["all_match"] is False
    divergent = [r for r in verdict2["rows"] if r["status"] == "diverge"]
    assert divergent and divergent[0]["step_id"] == "install-helper"


def test_replay_unknown_runset_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    import pytest

    with pytest.raises(FileNotFoundError):
        replay_runset("nope", repo_root=tmp_path, driver=object(), brain=object())
