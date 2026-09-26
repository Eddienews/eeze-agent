"""Mission UX: recipes, plain-language plans, result/source previews (nothing runs)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core import mission_ux
from eeze_agent.core.missions import MissionStore

PHOTO_PLAN = """name: square
source: avatar.png
steps:
  - id: crop
    op: crop
    x: 0
    y: 0
    width: 800
    height: 800
  - id: pop
    op: adjust
    contrast: 1.1
    saturation: 1.2
output: square.png
"""

VIDEO_PLAN = """name: vertical
sources: {a: a.mp4, b: b.mp4}
steps:
  - {id: t1, op: trim, input: a, start: 1, duration: 4}
  - {id: s1, op: scale, input: t1, size: [1080, 1920]}
  - {id: j, op: concat, inputs: [s1, b]}
output: j
"""


def test_recipes_are_complete():
    items = mission_ux.recipes()
    assert len(items) >= 5
    for r in items:
        assert r["kind"] in {"video", "photo", "3d", "task", "files"}
        assert r["goal"] and r["title"] and r["name"]


def test_describe_photo_and_video_in_plain_words():
    photo = mission_ux.describe_plan("photo", PHOTO_PLAN)
    assert photo[0].startswith("Edits “avatar.png”")
    assert "Crop a 800×800 area" in photo[1]
    assert "contrast ×1.1" in photo[2] and "saturation ×1.2" in photo[2]
    video = mission_ux.describe_plan("video", VIDEO_PLAN)
    assert any("Trim “a” to 4 s from 1 s" in line for line in video)
    assert any("1080×1920" in line for line in video)
    assert any(line.startswith("Join") for line in video)


def test_describe_never_raises_on_garbage():
    assert mission_ux.describe_plan("video", ":: not yaml [") == []
    assert mission_ux.describe_plan("3d", "- a list") == []


def test_output_files_only_inside_artifacts(tmp_path: Path):
    out = tmp_path / "artifacts" / "runs" / "rs1" / "run-01"
    out.mkdir(parents=True)
    (out / "final.mp4").write_bytes(b"x" * 10)
    (out / "thumb.png").write_bytes(b"x")
    (out / "edit-report.json").write_text("{}")
    files = mission_ux.output_files(tmp_path, str(out.parent))
    assert [f["name"] for f in files] == ["final.mp4", "thumb.png"]
    assert files[0]["url"] == "/artifacts/runs/rs1/run-01/final.mp4"
    assert mission_ux.output_files(tmp_path, str(tmp_path)) == []  # outside artifacts/


def test_source_file_resolution_refuses_traversal(tmp_path: Path):
    src = tmp_path / "photos"
    src.mkdir()
    (src / "a.png").write_bytes(b"x")
    (src / "notes.txt").write_text("x")
    (tmp_path / "secret.png").write_bytes(b"x")
    assert mission_ux.resolve_source_file(str(src), "a.png") == (src / "a.png").resolve()
    for bad in ("../secret.png", "..\\secret.png", "notes.txt", "", "missing.png"):
        assert mission_ux.resolve_source_file(str(src), bad) is None
    assert [f["name"] for f in mission_ux.source_files(str(src))] == ["a.png"]


def test_endpoints(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text("tok", encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    src = tmp_path / "photos"
    src.mkdir()
    (src / "avatar.png").write_bytes(b"\x89PNG fake")
    store = MissionStore(home)
    store.save({"id": "m1", "name": "Square", "kind": "photo", "goal": "g",
                "plan": PHOTO_PLAN, "sources": str(src)})
    out = tmp_path / "artifacts" / "runs" / "rs1"
    (out / "run-01").mkdir(parents=True)
    (out / "run-01" / "square.png").write_bytes(b"x")
    store.record_run("m1", runset_id="rs1", status="done", out_dir=str(out))

    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "tok"}).status_code == 200
    assert len(client.get("/api/recipes").json()["items"]) >= 5
    lines = client.post("/api/missions/describe", json={"kind": "photo", "plan": PHOTO_PLAN}).json()
    assert lines["lines"][0].startswith("Edits")
    outputs = client.get("/api/missions/m1/outputs").json()
    assert outputs["status"] == "done"
    assert outputs["files"][0]["url"] == "/artifacts/runs/rs1/run-01/square.png"
    source = outputs["sources"][0]
    assert source["name"] == "avatar.png"
    got = client.get(source["url"])
    assert got.status_code == 200 and got.content == b"\x89PNG fake"
    assert client.get("/api/missions/m1/source-file", params={"name": "../x.png"}).status_code == 404
    assert client.get("/api/missions/nope/outputs").status_code == 404


def test_setup_state_reports_creative_tools(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text("tok", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "tok"}).status_code == 200
    tools = client.get("/api/setup/state").json()["tools"]
    assert set(tools) == {"ffmpeg", "blender", "codex"}
    assert all(v is None or isinstance(v, str) for v in tools.values())


def test_effective_status_for_dead_runs_and_decided_approvals():
    from datetime import datetime, timedelta

    from eeze_agent.core.missions import effective_last_run

    old = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: DTZ005
    fresh = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")  # noqa: DTZ005
    assert effective_last_run({"status": "running", "at": old})["status"] == "interrupted"
    assert effective_last_run({"status": "running", "at": fresh})["status"] == "running"
    pending = {"status": "needs_approval", "approval_id": "ap-1", "at": fresh}
    assert effective_last_run(pending, approval_status=lambda _i: "expired")["status"] == "expired"
    assert effective_last_run(pending, approval_status=lambda _i: "pending")["status"] == "needs_approval"
    assert effective_last_run(None) is None


def test_draft_charges_the_missions_agent(tmp_path: Path, monkeypatch):
    from eeze_agent.agents.models import Agent
    from eeze_agent.core import missions, spend

    seen: dict = {}

    class FakeWriter:
        engine = "http"
        model = "openai/gpt-6-sol"

        def write_scene(self, goal, **kw):
            seen["agent"] = self.budget_agent
            raise missions.MissionError("stop here")

    monkeypatch.setattr("eeze_agent.brains.specwriter.SpecWriter", FakeWriter)
    agent = Agent(id="studio", name="Studio", budget_usd_daily=0.5)
    try:
        missions.draft(kind="3d", goal="a cube", home=tmp_path, budget_agent=agent)
    except missions.MissionError:
        pass
    assert seen.get("agent") is agent
    assert spend.budget_for(agent) == 0.5


def test_sources_accept_a_single_file_and_windows_quotes(tmp_path: Path):
    from eeze_agent.brains.specwriter import collect_sources, split_sources

    folder = tmp_path / "Pictures"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"x")
    (folder / "b.png").write_bytes(b"x")
    one = folder / "a.png"
    assert split_sources(f'"{one}"') == (folder, one)
    assert split_sources(str(folder)) == (folder, None)
    names, _facts = collect_sources(f'"{one}"')
    assert list(names) == ["a"]
    assert sorted(collect_sources(str(folder))[0]) == ["a", "b"]
    assert [f["name"] for f in mission_ux.source_files(str(one))] == ["a.png"]
    assert mission_ux.resolve_source_file(str(one), "b.png") is None
    assert mission_ux.resolve_source_file(str(one), "a.png") == one.resolve()


def test_intermediate_step_files_are_marked(tmp_path: Path):
    run = tmp_path / "artifacts" / "runs" / "rs" / "run-01"
    (run / "work").mkdir(parents=True)
    (run / "square.png").write_bytes(b"x")
    (run / "work" / "01-crop.png").write_bytes(b"x")
    files = mission_ux.output_files(tmp_path, str(run.parent))
    assert [(f["name"], f["step"]) for f in files] == [("square.png", False), ("01-crop.png", True)]


def test_portuguese_summaries_and_recipes():
    lines = mission_ux.describe_plan("photo", PHOTO_PLAN, lang="pt")
    assert lines[0].startswith("Edita “avatar.png”")
    assert "contraste ×1.1" in lines[2]
    assert all(r.get("title_pt") and r.get("goal_pt") for r in mission_ux.recipes())
