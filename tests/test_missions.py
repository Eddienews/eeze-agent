"""F7 — missions: store, edit, validate, materialize, gated run, schedule sync, API surface.

No model call here: the writers are faked where a draft is exercised (the real writers are covered by
their own tests). The run test goes through the real loop — and must PAUSE at the gate, which is the
point (a mission run is `install_exec`, so the operator's click is what starts Blender/ffmpeg).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.missions import (
    MissionDraftError,
    MissionError,
    MissionStore,
    draft,
    materialize,
    run_mission,
    sync_schedule,
    validate_plan,
)
from eeze_agent.core.routines import RoutineStore

REPO = Path(__file__).resolve().parents[1]
TOKEN = {"X-EEZE-Token": "test-token-123"}
SPEC_3D = (REPO / "specs" / "brand-3d.yaml").read_text(encoding="utf-8")
SPEC_PHOTO = """name: avatar
source: C:/fixtures/logo.png
steps:
  - id: focus
    op: crop
    x: 10
    y: 10
    width: 100
    height: 100
output: avatar.png
"""
TASK_GUI = (REPO / "tasks" / "notepad-gated-demo.yaml").read_text(encoding="utf-8")


def _env(tmp_path: Path, monkeypatch) -> MissionStore:
    monkeypatch.setenv("EEZE_MISSIONS", str(tmp_path / "missions"))
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    return MissionStore()


def _save(store: MissionStore, **over) -> dict:
    payload = {
        "id": "m1",
        "name": "Logo turntable",
        "kind": "3d",
        "goal": "the brand wordmark turntable",
        "plan": SPEC_3D,
        "plan_meta": {"draft_text": SPEC_3D},
    }
    payload.update(over)
    return store.save(payload)


# ---------------- store ----------------


def test_store_roundtrip_and_list_hides_the_plan(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    row = _save(store)
    assert row["has_plan"] is True and row["plan_chars"] == len(SPEC_3D)
    assert row["plan"] == SPEC_3D and row["plan_meta"]["edited"] is False
    listed = store.list()[0]
    assert "plan" not in listed and listed["has_plan"] is True
    assert listed["plan_meta"] == {"edited": False}  # draft_text never leaves the disk
    assert store.get("m1")["plan"] == SPEC_3D
    assert store.remove("m1") is True and store.get("m1") is None and store.remove("m1") is False


def test_store_is_atomic_and_id_safe(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store)
    assert [p.name for p in store.root.iterdir()] == ["m1.yaml"]  # no .tmp left behind
    for bad in ("../escape", "a/b", "", "a" * 61, "with space"):
        with pytest.raises(MissionError):
            store.save({"id": bad, "kind": "3d"})
    # ids normalize to lowercase instead of exploding
    assert _save(store, id="MiXeD")["id"] == "mixed"


def test_editing_the_plan_is_recorded_not_enforced(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store)
    edited = _save(store, plan=SPEC_3D + "\n# operator tweak\n")
    assert edited["plan_meta"]["edited"] is True
    assert edited["plan"].endswith("# operator tweak\n")  # the operator's text is kept verbatim
    back = _save(store, plan=SPEC_3D)
    assert back["plan_meta"]["edited"] is False


def test_partial_save_keeps_previous_fields(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store)
    again = store.save({"id": "m1", "name": "Renamed"})
    assert again["name"] == "Renamed" and again["plan"] == SPEC_3D and again["goal"]
    assert store.get("m1")["created_at"] == again["created_at"]


def test_schedule_validation_and_record_run(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store, schedule={"type": "daily", "at": "08:00"})
    assert store.get("m1")["schedule"] == {"type": "daily", "at": "08:00"}
    assert _save(store, schedule={"type": "every", "minutes": 30})["schedule"] == {"type": "every", "minutes": 30}
    for bad in ({"type": "cron"}, {"type": "daily", "at": "8h"}, {"type": "every", "minutes": 0}):
        with pytest.raises(MissionError):
            _save(store, schedule=bad)
    store.record_run("m1", runset_id="rs-1", status="needs_approval", approval_id="ap-1", out_dir="/tmp/x")
    last = store.get("m1")["last_run"]
    assert last["runset_id"] == "rs-1" and last["status"] == "needs_approval" and last["approval_id"] == "ap-1"


# ---------------- validate ----------------


def test_validate_uses_the_runner_loaders(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert validate_plan(kind="3d", plan_text=SPEC_3D)["ok"] is True
    assert validate_plan(kind="task", plan_text=TASK_GUI)["ok"] is True
    bad = validate_plan(kind="3d", plan_text="name: x\nscene: {}\n")
    assert bad["ok"] is False and bad["errors"] and "validation error" in bad["errors"][0].lower()
    assert validate_plan(kind="3d", plan_text="")["errors"] == ["the plan is empty — generate a draft first"]
    assert validate_plan(kind="nope", plan_text=SPEC_3D)["errors"] == ["unknown kind 'nope'"]
    # a video plan with no sources dir: the feasibility check says so instead of shrugging
    vid = "name: v\nsources: {clip: /nope/clip.mp4}\nsteps: [{id: t, op: trim, source: clip, start: 0, end: 1}]\noutput: out.mp4\n"
    problems = validate_plan(kind="video", plan_text=vid, sources=str(tmp_path / "missing"))
    assert problems["ok"] is False and problems["errors"]


# ---------------- materialize ----------------


def test_materialize_creative_writes_a_runnable_task(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store)
    task_path = materialize(store.get("m1"))
    assert task_path.name == "task.yaml" and (task_path.parent / "spec.yaml").exists()
    text = task_path.read_text(encoding="utf-8")
    assert "name: mission-m1" in text and "run_script" in text
    assert "render-report.json" in text  # verification reads the vertical's own report
    assert "eeze" in text and "spec" in text
    from eeze_agent.core.tasks import load_task

    task = load_task(task_path)
    assert task.app == "" and task.steps[0].command.startswith('"{eeze}" 3d')


def test_photo_mission_validates_and_materializes_gated_task(tmp_path: Path, monkeypatch):
    import eeze_agent.core.missions as missions_mod
    from eeze_agent.core.risk import classify_step
    from eeze_agent.core.tasks import load_task

    store = _env(tmp_path, monkeypatch)
    _save(store, kind="photo", plan=SPEC_PHOTO, sources=str(tmp_path))
    facts = {"logo": {"path": "C:/fixtures/logo.png", "kind": "image",
                      "codec_v": "png", "width": 1254, "height": 1254}}
    monkeypatch.setattr(missions_mod, "_photo_sources", lambda folder: ({"logo": facts["logo"]["path"]}, facts))
    assert validate_plan(kind="photo", plan_text=SPEC_PHOTO, sources=str(tmp_path))["ok"] is True
    bad = SPEC_PHOTO.replace("x: 10", "x: 1240")
    result = validate_plan(kind="photo", plan_text=bad, sources=str(tmp_path))
    assert result["ok"] is False and "outside current" in result["errors"][0]
    task_path = materialize(store.get("m1"))
    task = load_task(task_path)
    assert task.steps[0].command.startswith('"{eeze}" photo')
    assert "edit-report.json" in task.steps[0].verify_code
    assert "avatar.png" in task.steps[0].verify_code
    assert classify_step(task.steps[0], task).risk_class == "install_exec"
    assert (task_path.parent / "spec.yaml").read_text(encoding="utf-8") == SPEC_PHOTO


def test_materialize_task_kind_keeps_the_plan_verbatim(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store, kind="task", plan=TASK_GUI)
    task_path = materialize(store.get("m1"))
    assert task_path.read_text(encoding="utf-8") == TASK_GUI


def test_materialize_refuses_without_a_plan(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store, plan="")
    with pytest.raises(MissionError, match="no plan yet"):
        materialize(store.get("m1"))


def test_materialize_refuses_garbage_text(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store, plan="name: x\nscene: {}\n")
    with pytest.raises(Exception) as exc:  # the loader's own reason travels
        materialize(store.get("m1"))
    assert "validation error" in str(exc.value).lower()


# ---------------- draft (writers faked: no model call) ----------------


class _FakeWriter:
    """Stands in for SpecWriter: returns a plan, or refuses like the real one does."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.model = "codex:gpt-6-sol"

    def write_scene(self, goal, *, out_dir, name_hint="x"):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if self.fail:
            (out_dir / "write-report.json").write_text(
                json.dumps({"model": self.model, "attempts": [{"attempt": 1, "error": "feasibility: boom"}]}),
                encoding="utf-8",
            )
            raise RuntimeError("no valid spec after 3 attempt(s) — last error: feasibility: boom")
        return _FakeResult(SPEC_3D)

    def write_video(self, goal, *, sources, facts, out_dir, name_hint="x"):
        return self.write_scene(goal, out_dir=out_dir, name_hint=name_hint)


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.yaml_text = text
        self.model = "codex:gpt-6-sol"
        self.attempts = [{"attempt": 1, "error": None}]
        self.tokens = 80025
        self.cost_usd = 0.0


def test_draft_reports_the_writers_real_numbers(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_MISSIONS", str(tmp_path / "missions"))
    import eeze_agent.brains.specwriter as specwriter_mod

    monkeypatch.setattr(specwriter_mod, "SpecWriter", lambda *a, **k: _FakeWriter())
    out = draft(kind="3d", goal="a turntable", name_hint="turntable", home=tmp_path / "home")
    assert out["plan"] == SPEC_3D and out["plan_kind"] == "3d"
    assert out["model"] == "codex:gpt-6-sol" and out["tokens"] == 80025 and out["cost_usd"] == 0.0
    assert out["attempts"][0]["error"] is None and out["ms"] >= 0


def test_draft_refusal_carries_the_attempts(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_MISSIONS", str(tmp_path / "missions"))
    import eeze_agent.brains.specwriter as specwriter_mod

    monkeypatch.setattr(specwriter_mod, "SpecWriter", lambda *a, **k: _FakeWriter(fail=True))
    with pytest.raises(MissionDraftError) as exc:
        draft(kind="3d", goal="a turntable", home=tmp_path / "home")
    assert exc.value.attempts and exc.value.attempts[0]["error"] == "feasibility: boom"
    assert exc.value.model == "codex:gpt-6-sol"


def test_draft_refuses_empty_goal_and_video_without_sources(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_MISSIONS", str(tmp_path / "missions"))
    with pytest.raises(MissionError, match="goal is empty"):
        draft(kind="3d", goal="   ", home=tmp_path / "home")
    with pytest.raises(MissionError, match="sources dir"):
        draft(kind="video", goal="cut it", home=tmp_path / "home")
    with pytest.raises(MissionError, match="unknown kind"):
        draft(kind="podcast", goal="x", home=tmp_path / "home")


def test_photo_draft_refuses_paid_engine_before_call(tmp_path: Path, monkeypatch):
    import eeze_agent.brains.specwriter as specwriter_mod

    _env(tmp_path, monkeypatch)

    class PaidWriter:
        engine = "http"

        def write_photo(self, *_args, **_kwargs):
            raise AssertionError("paid provider must not be called")

    monkeypatch.setattr(specwriter_mod, "SpecWriter", lambda: PaidWriter())
    with pytest.raises(MissionError, match="local Codex engine"):
        draft(kind="photo", goal="make a portrait", sources=str(tmp_path))


def test_photo_sources_only_accepts_probed_images(tmp_path: Path):
    import shutil

    from eeze_agent.core.missions import _photo_sources
    from eeze_agent.verticals.video.probe import find_tools

    try:
        find_tools()
    except FileNotFoundError:
        pytest.skip("ffmpeg/ffprobe not installed")
    shutil.copy2(REPO / "ui" / "public" / "eeze.png", tmp_path / "mascot.png")
    (tmp_path / "not-an-image.jpg").write_bytes(b"video bytes")
    names, facts = _photo_sources(str(tmp_path))
    assert list(names) == ["mascot"]
    assert facts["mascot"]["kind"] == "image"
    assert (facts["mascot"]["width"], facts["mascot"]["height"]) == (1254, 1254)


# ---------------- schedule sync ----------------


def test_schedule_sync_upserts_and_removes_the_routine(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store, schedule={"type": "daily", "at": "09:30"})
    out = sync_schedule(store.get("m1"))
    assert out["routine_id"] == "mission:m1"
    routines = RoutineStore()
    row = routines.get("mission:m1")
    assert row["kind"] == "task" and row["schedule"] == {"type": "daily", "at": "09:30"}
    assert row["name"].startswith("Mission ·") and Path(row["params"]["task_path"]).exists()
    off = sync_schedule(_save(store, schedule={"type": "on_demand"}))
    assert off == {"removed": True} and routines.get("mission:m1") is None


# ---------------- run (the real loop; must pause at the gate) ----------------


def test_run_records_the_run_and_gates_install_exec(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agents.yaml").write_text("agents:\n  - id: default\n    name: Default\n", encoding="utf-8")
    result = run_mission("m1", repo_root=repo)
    assert result["status"] == "needs_approval", result
    assert result["runset_id"].endswith("-mission-m1")
    approvals = ApprovalStore().list(limit=10)
    assert approvals and approvals[0]["task"] == "mission-m1"
    assert approvals[0]["risk_class"] == "install_exec"
    assert approvals[0]["status"] == "pending"
    last = store.get("m1")["last_run"]
    assert last["status"] == "needs_approval" and last["approval_id"] == result["approval_id"]
    summary = json.loads((Path(result["out_dir"]) / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "needs_approval"


def test_photo_mission_pauses_before_running_local_editor(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store, kind="photo", plan=SPEC_PHOTO, sources=str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agents.yaml").write_text("agents:\n  - id: default\n    name: Default\n", encoding="utf-8")
    result = run_mission("m1", repo_root=repo)
    assert result["status"] == "needs_approval"
    approval = ApprovalStore().get(result["approval_id"])
    assert approval["risk_class"] == "install_exec" and approval["action_digest"]
    out = Path(result["out_dir"])
    assert not (out / "run-01" / "avatar.png").exists()
    journal = (out / "journal.jsonl").read_text(encoding="utf-8")
    assert '"kind": "step_end"' not in journal


def test_run_without_a_plan_is_an_error_not_a_crash(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store, plan="")
    out = run_mission("m1", repo_root=tmp_path)
    assert out["status"] == "error" and "no plan yet" in out["error"]
    assert run_mission("nope", repo_root=tmp_path)["error"].startswith("unknown mission")


def test_resume_updates_only_the_matching_mission_status(tmp_path: Path, monkeypatch):
    from eeze_agent.agents.models import AgentContext
    from eeze_agent.agents.registry import load_registry
    from eeze_agent.core.journal import RunJournal
    from eeze_agent.core.loop import run_set
    from eeze_agent.core.risk import policy_for_agent
    from eeze_agent.core.tasks import load_task

    store = _env(tmp_path, monkeypatch)
    plan = ("name: mission-m1\napp: ''\nsteps:\n"
            "  - id: make\n    action: run_script\n"
            "    command: echo done > done.txt\n    retries: 0\n"
            "    verify_code: file_exists|{run_dir}/done.txt\n")
    _save(store, kind="task", goal="Create a local file", plan=plan)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agents.yaml").write_text("agents:\n  - id: default\n    name: Default\n", encoding="utf-8")
    paused = run_mission("m1", repo_root=repo)
    assert paused["status"] == "needs_approval"
    approvals = ApprovalStore()
    approval_id = paused["approval_id"]
    approvals.decide(approval_id, "approve", decided_by="tester")
    state = json.loads(approvals.run_state_for(approval_id)["payload"])
    agent = load_registry(repo).get("default")
    ctx = AgentContext(agent=agent)
    ctx.runset_id = paused["runset_id"]
    journal = RunJournal(repo / "artifacts" / "runs", paused["runset_id"], agent_id=agent.id)
    try:
        summary = run_set(
            task=load_task(Path(state["task_path"])), agent_ctx=ctx, driver=object(),
            brain=None, journal=journal, runs=1, out_dir=Path(paused["out_dir"]),
            policy=policy_for_agent(agent.permissions), approvals=approvals,
            task_path=Path(state["task_path"]), resume_state=state,
        )
    finally:
        journal.close()
    assert summary["success_rate"] == "1/1"
    assert (Path(paused["out_dir"]) / "run-01" / "done.txt").exists()
    saved = store.get("m1")
    assert saved["last_run"]["status"] == "done"
    assert saved["last_run"]["runset_id"] == paused["runset_id"]
    assert saved["goal"] == "Create a local file" and saved["plan"] == plan


def test_resume_rejects_stale_or_foreign_mission_updates(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store)
    store.record_run("m1", runset_id="new-run", status="needs_approval", approval_id="new-ap")
    task_path = store.plan_dir("m1") / "task.yaml"
    task_path.write_text("name: x\n", encoding="utf-8")
    summary = {"status": "done", "success_rate": "1/1", "runs_completed": 1, "task_runs": 1}
    assert not store.record_resume(task_path=task_path, runset_id="old-run", approval_id="new-ap", summary=summary)
    assert not store.record_resume(task_path=task_path, runset_id="new-run", approval_id="old-ap", summary=summary)
    foreign = tmp_path / "foreign" / "m1" / "task.yaml"
    assert not store.record_resume(task_path=foreign, runset_id="new-run", approval_id="new-ap", summary=summary)
    assert store.get("m1")["last_run"]["status"] == "needs_approval"
    assert store.get("m1")["plan"] == SPEC_3D


def test_resume_records_failed_run_as_error(tmp_path: Path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    _save(store)
    store.record_run("m1", runset_id="failed-run", status="needs_approval", approval_id="ap-1")
    task_path = store.plan_dir("m1") / "task.yaml"
    assert store.record_resume(
        task_path=task_path, runset_id="failed-run", approval_id="ap-1",
        summary={"status": "done", "success_rate": "0/1", "runs_completed": 1, "task_runs": 1},
    )
    assert store.get("m1")["last_run"]["status"] == "error"


# ---------------- API ----------------


def _client(tmp_path: Path, monkeypatch, *, spawned: list | None = None) -> TestClient:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "api.token").write_text(TOKEN["X-EEZE-Token"], encoding="utf-8")
    monkeypatch.setenv("EEZE_MISSIONS", str(home / "missions"))
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    if spawned is not None:
        import eeze_agent.core.routines as routines_mod

        monkeypatch.setattr(
            routines_mod, "spawn_detached", lambda argv, cwd, log_path: spawned.append(list(argv))
        )
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": TOKEN["X-EEZE-Token"]}).status_code == 200
    return client


def test_api_crud_token_gate_and_honest_errors(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/missions").json()["total"] == 0
    assert client.post("/api/missions", json={"id": "m1", "kind": "3d"}).status_code == 401
    assert (
        client.post("/api/missions", json={"id": "m1", "kind": "3d"}, headers={"X-EEZE-Token": "wrong"}).status_code
        == 401
    )
    body = {"id": "m1", "name": "Logo turntable", "kind": "3d", "goal": "turntable", "plan": SPEC_3D,
            "schedule": {"type": "on_demand"}}
    saved = client.post("/api/missions", json=body, headers=TOKEN)
    assert saved.status_code == 200, saved.text
    row = saved.json()
    assert row["id"] == "m1" and row["has_plan"] and row["plan"] == SPEC_3D
    assert row["note"] == "saved — on demand (no schedule attached)"
    assert client.get("/api/missions/m1").json()["name"] == "Logo turntable"
    assert client.get("/api/missions/nope").status_code == 404
    # bad schedule -> 422 with the reason, not a 500
    bad = client.post("/api/missions", json={**body, "schedule": {"type": "daily", "at": "8h"}}, headers=TOKEN)
    assert bad.status_code == 422 and "invalid daily time" in bad.json()["error"]["message"]
    # validate is stateless compute: open, no token needed
    assert client.post("/api/missions/m1/validate", json={"plan": SPEC_3D}).json()["ok"] is True
    garbage = client.post("/api/missions/m1/validate", json={"plan": "name: x\n"}).json()
    assert garbage["ok"] is False and garbage["errors"]
    assert client.delete("/api/missions/m1", headers=TOKEN).json()["removed"] is True
    assert client.get("/api/missions").json()["total"] == 0


def test_api_run_needs_a_plan_and_a_token(tmp_path: Path, monkeypatch):
    spawned: list = []
    client = _client(tmp_path, monkeypatch, spawned=spawned)
    client.post("/api/missions", json={"id": "m1", "kind": "3d", "goal": "x"}, headers=TOKEN)  # no plan
    assert client.post("/api/missions/m1/run", headers=TOKEN).status_code == 409
    assert client.post("/api/missions/m1/run").status_code == 401
    client.post("/api/missions", json={"id": "m1", "kind": "3d", "goal": "x", "plan": SPEC_3D}, headers=TOKEN)
    ok = client.post("/api/missions/m1/run", headers=TOKEN)
    assert ok.status_code == 200 and ok.json()["spawned"] is True
    assert spawned == [["mission", "run", "m1"]]
    assert ok.json()["log"].endswith("run-m1.log")


def test_api_schedule_sync_and_delete_cleanup(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = {"id": "m1", "kind": "3d", "goal": "x", "plan": SPEC_3D, "schedule": {"type": "daily", "at": "07:15"}}
    row = client.post("/api/missions", json=body, headers=TOKEN).json()
    assert row["note"] == "saved — scheduled as routine mission:m1"
    assert RoutineStore().get("mission:m1")["schedule"] == {"type": "daily", "at": "07:15"}
    row = client.post("/api/missions", json={**body, "schedule": {"type": "on_demand"}}, headers=TOKEN).json()
    assert "previous schedule was removed" in row["note"]
    client.post("/api/missions", json=body, headers=TOKEN)
    out = client.delete("/api/missions/m1", headers=TOKEN).json()
    assert out["removed"] is True and out["routine_removed"] is True
    assert RoutineStore().get("mission:m1") is None


def test_api_scheduled_mission_without_a_plan_says_so(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = {"id": "m1", "kind": "3d", "goal": "x", "schedule": {"type": "every", "minutes": 5}}
    row = client.post("/api/missions", json=body, headers=TOKEN).json()
    assert "needs a plan first" in row["note"]
    assert RoutineStore().get("mission:m1") is None


def test_api_photo_draft_and_validate_without_real_model(tmp_path: Path, monkeypatch):
    import eeze_agent.brains.specwriter as specwriter_mod
    from eeze_agent.core import missions as missions_mod

    client = _client(tmp_path, monkeypatch)
    facts = {"logo": {"path": "C:/fixtures/logo.png", "kind": "image",
                      "codec_v": "png", "width": 1254, "height": 1254}}
    monkeypatch.setattr(missions_mod, "_photo_sources", lambda folder: ({"logo": facts["logo"]["path"]}, facts))

    class FakePhotoWriter:
        engine = "codex"

        def write_photo(self, goal, *, sources, facts, out_dir, name_hint):
            assert sources["logo"] == "C:/fixtures/logo.png"
            return _FakeResult(SPEC_PHOTO)

    monkeypatch.setattr(specwriter_mod, "SpecWriter", lambda: FakePhotoWriter())
    body = {"kind": "photo", "goal": "Make a square portrait", "sources": str(tmp_path)}
    assert client.post("/api/missions/draft", json=body).status_code == 401
    draft_result = client.post("/api/missions/draft", json=body, headers=TOKEN)
    assert draft_result.status_code == 200, draft_result.text
    assert draft_result.json()["plan_kind"] == "photo" and draft_result.json()["plan"] == SPEC_PHOTO
    checked = client.post("/api/missions/validate", json={"kind": "photo", "plan": SPEC_PHOTO,
                                                             "sources": str(tmp_path)})
    assert checked.json() == {"ok": True, "errors": []}
    saved = client.post("/api/missions", json={"id": "portrait", "kind": "photo",
                                                "plan": SPEC_PHOTO, "sources": str(tmp_path)}, headers=TOKEN)
    assert saved.status_code == 200 and saved.json()["kind"] == "photo"


def test_api_draft_refusal_is_a_422_with_attempts(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    import eeze_agent.brains.specwriter as specwriter_mod

    monkeypatch.setattr(specwriter_mod, "SpecWriter", lambda *a, **k: _FakeWriter(fail=True))
    refused = client.post("/api/missions/draft", json={"kind": "3d", "goal": "a turntable"}, headers=TOKEN)
    assert refused.status_code == 422
    error = refused.json()["error"]
    assert "no valid spec" in error["message"]
    assert error["detail"]["attempts"][0]["error"] == "feasibility: boom"
    assert error["detail"]["model"] == "codex:gpt-6-sol"
    assert client.post("/api/missions/draft", json={"kind": "3d", "goal": "x"}).status_code == 401
