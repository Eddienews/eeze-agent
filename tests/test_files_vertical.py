"""Files vertical: rename in sequence, organize, duplicates — preview, apply, undo, safety."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from eeze_agent.verticals.files import FilesSpec, apply_plan, plan_changes, undo
from eeze_agent.verticals.files.exif import date_taken
from eeze_agent.verticals.files.runner import FilesError


def _jpeg_with_date(path: Path, stamp: str) -> None:
    """A tiny JPEG whose EXIF IFD0 carries DateTime (tag 0x0132) = stamp."""
    value = stamp.encode("ascii") + b"\x00"
    ifd = struct.pack("<H", 1) + struct.pack("<HHII", 0x0132, 2, len(value), 26) + struct.pack("<I", 0)
    tiff = b"II*\x00" + struct.pack("<I", 8) + ifd + value
    app1 = b"Exif\x00\x00" + tiff
    path.write_bytes(b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9")


def _folder(tmp_path: Path, names: list[str]) -> Path:
    folder = tmp_path / "Parque"
    folder.mkdir()
    for name in names:
        (folder / name).write_bytes(name.encode())
    return folder


def _spec(folder: Path, **kw) -> FilesSpec:
    return FilesSpec(name="t", folder=str(folder), **kw)


def test_rename_in_natural_order_with_padding(tmp_path: Path):
    folder = _folder(tmp_path, ["img10.jpg", "img2.jpg", "img1.jpg", "notes.txt"])
    plan = plan_changes(_spec(folder, op="rename", pattern="park{n:03}"))
    assert plan["changes"] == [
        {"from": "img1.jpg", "to": "park001.jpg"},
        {"from": "img2.jpg", "to": "park002.jpg"},
        {"from": "img10.jpg", "to": "park003.jpg"},
    ]
    assert plan["conflicts"] == []
    assert (folder / "img1.jpg").exists()  # preview touches nothing


def test_apply_then_undo_restores_everything(tmp_path: Path):
    folder = _folder(tmp_path, ["img001.jpg", "img002.jpg", "img003.JPG"])
    report = apply_plan(_spec(folder, op="rename", pattern="park{n:03}"), tmp_path / "out")
    assert report["applied"] == 3
    assert sorted(p.name for p in folder.iterdir()) == ["park001.jpg", "park002.jpg", "park003.JPG"]
    assert (folder / "park001.jpg").read_bytes() == b"img001.jpg"  # content travels with the name
    undo(tmp_path / "out" / "files-report.json")
    assert sorted(p.name for p in folder.iterdir()) == ["img001.jpg", "img002.jpg", "img003.JPG"]
    with pytest.raises(FilesError):
        undo(tmp_path / "out" / "files-report.json")  # only once


def test_swaps_and_chains_are_safe(tmp_path: Path):
    folder = _folder(tmp_path, ["photo2.jpg", "photo1.jpg"])
    # order by name reversed via pattern {n} starting at 1: photo1->photo1 (skip), photo2->photo2
    report = apply_plan(_spec(folder, op="rename", pattern="photo{n}", start=2), tmp_path / "o")
    # photo1 -> photo2, photo2 -> photo3: a chain that would overwrite without temp names
    assert report["applied"] == 2
    assert (folder / "photo2.jpg").read_bytes() == b"photo1.jpg"
    assert (folder / "photo3.jpg").read_bytes() == b"photo2.jpg"


def test_existing_name_outside_the_batch_refuses_everything(tmp_path: Path):
    folder = _folder(tmp_path, ["b.jpg", "a.jpg"])
    (folder / "park001.jpg").mkdir()  # a FOLDER with the target name: not part of the batch
    spec = _spec(folder, op="rename", pattern="park{n:03}")
    plan = plan_changes(spec)
    assert any("park001.jpg already exists" in c for c in plan["conflicts"])
    with pytest.raises(FilesError):
        apply_plan(spec, tmp_path / "o")
    assert sorted(p.name for p in folder.iterdir()) == ["a.jpg", "b.jpg", "park001.jpg"]
    assert json.loads((tmp_path / "o" / "files-report.json").read_text())["applied"] == 0


def test_in_batch_chain_where_a_target_is_another_source(tmp_path: Path):
    folder = _folder(tmp_path, ["b.jpg", "park001.jpg"])
    # natural order: b.jpg -> park001.jpg, park001.jpg -> park002.jpg (needs temp names)
    report = apply_plan(_spec(folder, op="rename", pattern="park{n:03}"), tmp_path / "o")
    assert report["applied"] == 2
    assert (folder / "park001.jpg").read_bytes() == b"b.jpg"
    assert (folder / "park002.jpg").read_bytes() == b"park001.jpg"


def test_duplicates_only_report(tmp_path: Path):
    folder = _folder(tmp_path, ["a.jpg", "b.jpg", "c.jpg"])
    (folder / "b.jpg").write_bytes(b"a.jpg")  # same content as a.jpg
    plan = plan_changes(_spec(folder, op="duplicates"))
    assert plan["duplicates"] == [["a.jpg", "b.jpg"]]
    assert plan["changes"] == []
    report = apply_plan(_spec(folder, op="duplicates"), tmp_path / "o")
    assert report["applied"] == 0 and len(list(folder.iterdir())) == 3  # nothing deleted


def test_organize_by_month_uses_date_taken_and_undo_removes_folders(tmp_path: Path):
    folder = tmp_path / "Fotos"
    folder.mkdir()
    _jpeg_with_date(folder / "a.jpg", "2026:03:14 10:00:00")
    _jpeg_with_date(folder / "b.jpg", "2026:04:01 09:30:00")
    assert date_taken(folder / "a.jpg").month == 3
    report = apply_plan(_spec(folder, op="organize", by="month"), tmp_path / "o")
    assert (folder / "2026-03" / "a.jpg").exists() and (folder / "2026-04" / "b.jpg").exists()
    assert report["applied"] == 2
    undo(tmp_path / "o" / "files-report.json")
    assert sorted(p.name for p in folder.iterdir()) == ["a.jpg", "b.jpg"]


def test_rename_by_date_taken(tmp_path: Path):
    folder = tmp_path / "Viagem"
    folder.mkdir()
    _jpeg_with_date(folder / "z.jpg", "2025:01:01 08:00:00")
    _jpeg_with_date(folder / "a.jpg", "2025:06:01 08:00:00")
    plan = plan_changes(_spec(folder, op="rename", pattern="viagem_{n}_{date}", order="taken"))
    assert plan["changes"] == [
        {"from": "z.jpg", "to": "viagem_1_2025-01-01.jpg"},
        {"from": "a.jpg", "to": "viagem_2_2025-06-01.jpg"},
    ]


@pytest.mark.parametrize("pattern", ["park", "../x{n}", "a/b{n}", "x{n}{ext}", "{bogus}{n}", "a:b{n}"])
def test_bad_patterns_are_refused(tmp_path: Path, pattern: str):
    with pytest.raises(ValidationError):
        FilesSpec(name="t", folder=str(tmp_path), op="rename", pattern=pattern)


def test_undo_refuses_when_files_moved_since(tmp_path: Path):
    folder = _folder(tmp_path, ["a.jpg"])
    apply_plan(_spec(folder, op="rename", pattern="p{n}"), tmp_path / "o")
    (folder / "p1.jpg").rename(folder / "moved.jpg")
    with pytest.raises(FilesError):
        undo(tmp_path / "o" / "files-report.json")
    assert (folder / "moved.jpg").exists()


def test_preview_and_undo_endpoints(tmp_path: Path, monkeypatch):
    from eeze_agent.api.app import create_app
    from eeze_agent.core.missions import MissionStore

    folder = _folder(tmp_path, ["img1.jpg", "img2.jpg"])
    plan = f"name: t\nfolder: '{folder}'\nop: rename\npattern: park{{n:03}}\n"
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text("tok", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "tok"}).status_code == 200
    preview = client.post("/api/files/preview", json={"plan": plan}).json()
    assert preview["ok"] and preview["total_changes"] == 2
    assert preview["changes"][0] == {"from": "img1.jpg", "to": "park001.jpg"}
    bad = client.post("/api/files/preview", json={"plan": "op: nope"}).json()
    assert bad["ok"] is False

    out = tmp_path / "artifacts" / "runs" / "20260926-010000-mission-m1" / "run-01"
    report = apply_plan(_spec(folder, op="rename", pattern="park{n:03}"), out)
    assert report["applied"] == 2
    store = MissionStore(home)
    store.save({"id": "m1", "name": "R", "kind": "files", "goal": "g", "plan": plan,
                "sources": str(folder)})
    store.record_run("m1", runset_id="rs1", status="done", out_dir=str(out.parent))
    outputs = client.get("/api/missions/m1/outputs").json()
    assert outputs["report"]["applied"] == 2 and outputs["report"]["changes"][1]["to"] == "park002.jpg"
    headers = {"X-EEZE-Token": "tok"}
    assert client.post("/api/missions/m1/undo").status_code == 401
    done = client.post("/api/missions/m1/undo", headers=headers)
    assert done.status_code == 200 and done.json()["restored"] == 2
    assert sorted(p.name for p in folder.iterdir()) == ["img1.jpg", "img2.jpg"]
    assert client.post("/api/missions/m1/undo", headers=headers).status_code == 404  # nothing left
    assert json.loads((out / "files-report.json").read_text())["undone"] is True


def test_mission_validation_and_materialize_for_files(tmp_path: Path, monkeypatch):
    import yaml

    from eeze_agent.core import missions

    folder = _folder(tmp_path, ["a.jpg"])
    plan = f"name: t\nfolder: '{folder}'\nop: rename\npattern: p{{n}}\n"
    assert missions.validate_plan(kind="files", plan_text=plan, sources=str(folder))["ok"]
    other = tmp_path / "other"
    other.mkdir()
    wrong = missions.validate_plan(kind="files", plan_text=plan, sources=str(other))
    assert not wrong["ok"] and "folder must be exactly" in wrong["errors"][0]
    monkeypatch.setattr(missions, "_eeze_exe", lambda: "eeze")
    task_path = missions.materialize({"id": "f1", "kind": "files", "plan": plan}, home=tmp_path / "h")
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    assert task["steps"][0]["command"].startswith('"{eeze}" files "{spec}"')
    assert "files-report.json" in task["steps"][0]["verify_code"]


def test_describe_files_plan():
    from eeze_agent.core.mission_ux import describe_plan

    lines = describe_plan("files", "name: t\nfolder: C:/x\nop: rename\npattern: park{n:03}\norder: taken\n")
    assert "Rename" in lines[0] and "park{n:03}" in lines[1] and "taken" in lines[1]


def test_draft_writes_a_files_plan_from_portuguese(tmp_path: Path, monkeypatch):
    from eeze_agent.brains import specwriter
    from eeze_agent.core import missions

    folder = _folder(tmp_path, ["img001.jpg", "img002.jpg"])
    seen: dict = {}

    def fake_client(system: str, user: str):
        seen["system"], seen["user"] = system, user
        return (json.dumps({"name": "parque", "folder": str(folder), "op": "rename",
                            "pattern": "park{n:03}", "order": "name"}), 321)

    real = specwriter.SpecWriter

    class Writer(real):
        def __init__(self, *a, **k):
            super().__init__(client=fake_client, model="openai/gpt-6-luna")

    monkeypatch.setattr(specwriter, "SpecWriter", Writer)
    out = missions.draft(kind="files", goal="renomeie img001, img002 para park001, park002",
                         sources=f'"{folder}"', home=tmp_path / "h")
    assert "pattern: park{n:03}" in out["plan"]
    assert "FILES SPEC" in seen["system"] and str(folder) in seen["user"]
    assert missions.validate_plan(kind="files", plan_text=out["plan"], sources=str(folder))["ok"]


def test_failed_chain_rolls_everything_back_by_name(tmp_path: Path, monkeypatch):
    from eeze_agent.verticals.files import runner

    folder = _folder(tmp_path, ["a.jpg", "b.jpg", "c.jpg"])
    real = runner._move
    calls = {"n": 0}

    def flaky(src, dst):
        # phase 1 = 3 moves to temp; fail on the 3rd placement (a locked file, OneDrive…)
        calls["n"] += 1
        if calls["n"] == 6:
            raise PermissionError("locked by another program")
        return real(src, dst)

    monkeypatch.setattr(runner, "_move", flaky)
    with pytest.raises(FilesError) as err:
        apply_plan(_spec(folder, op="rename", pattern="{name}x"), tmp_path / "o")
    assert "every file was put back" in str(err.value)
    assert sorted(p.name for p in folder.iterdir()) == ["a.jpg", "b.jpg", "c.jpg"]
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        assert (folder / name).read_bytes() == name.encode()
    report = json.loads((tmp_path / "o" / "files-report.json").read_text())
    assert report["status"] == "rolled_back" and report["applied"] == 0


def test_interrupted_batch_can_still_be_undone(tmp_path: Path, monkeypatch):
    from eeze_agent.verticals.files import runner

    folder = _folder(tmp_path, ["a.jpg", "b.jpg"])

    class Crash(BaseException):
        pass

    real = runner._move
    calls = {"n": 0}

    def crash_after_phase1(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:  # both files already under temporary names: power cut
            raise Crash()
        return real(src, dst)

    monkeypatch.setattr(runner, "_move", crash_after_phase1)
    with pytest.raises(Crash):
        apply_plan(_spec(folder, op="rename", pattern="p{n}"), tmp_path / "o")
    left = sorted(p.name for p in folder.iterdir())
    assert all(n.startswith(".eeze-tmp-") and n.endswith(("--a.jpg", "--b.jpg")) for n in left)
    monkeypatch.setattr(runner, "_move", real)
    assert undo(tmp_path / "o" / "files-report.json")["restored"] == 2
    assert sorted(p.name for p in folder.iterdir()) == ["a.jpg", "b.jpg"]


def test_undo_of_renumbering(tmp_path: Path):
    folder = _folder(tmp_path, ["p2.jpg", "p3.jpg"])
    apply_plan(_spec(folder, op="rename", pattern="p{n}"), tmp_path / "o")
    assert (folder / "p1.jpg").read_bytes() == b"p2.jpg"
    undo(tmp_path / "o" / "files-report.json")
    assert (folder / "p2.jpg").read_bytes() == b"p2.jpg"
    assert (folder / "p3.jpg").read_bytes() == b"p3.jpg"


def test_hidden_and_system_files_are_never_touched(tmp_path: Path):
    folder = _folder(tmp_path, ["a.jpg", "desktop.ini", "Thumbs.db", "~$doc.docx", ".hidden.jpg"])
    plan = plan_changes(_spec(folder, op="rename", pattern="x{n}", include="all"))
    assert [c["from"] for c in plan["changes"]] == ["a.jpg"]


def test_organize_undo_keeps_preexisting_empty_folders(tmp_path: Path):
    folder = tmp_path / "F"
    folder.mkdir()
    _jpeg_with_date(folder / "a.jpg", "2026:03:14 10:00:00")
    (folder / "2025-01").mkdir()  # the owner's own empty folder
    apply_plan(_spec(folder, op="organize", by="month"), tmp_path / "o")
    undo(tmp_path / "o" / "files-report.json")
    assert (folder / "2025-01").is_dir() and not (folder / "2026-03").exists()


def test_files_missions_are_destructive_and_refuse_grants(tmp_path: Path, monkeypatch):
    import yaml

    from eeze_agent.api.app import create_app
    from eeze_agent.core import missions
    from eeze_agent.core.approvals import ApprovalStore

    folder = _folder(tmp_path, ["a.jpg"])
    plan = f"name: t\nfolder: '{folder}'\nop: rename\npattern: p{{n}}\n"
    monkeypatch.setattr(missions, "_eeze_exe", lambda: "eeze")
    task = yaml.safe_load(missions.materialize({"id": "f1", "kind": "files", "plan": plan},
                                               home=tmp_path / "h").read_text(encoding="utf-8"))
    assert task["steps"][0]["risk"] == "destructive"

    db = tmp_path / "e.db"
    monkeypatch.setenv("EEZE_DB", str(db))
    store = ApprovalStore(db)
    aid = store.request(runset_id="rs", task="mission-f1", task_path="", agent_id="default",
                        run_index=1, step_id="run", step_index=0, action="run_script",
                        risk_class="destructive", reason="r", action_digest="d" * 64,
                        run_state=lambda a: {"approval_id": a})
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text("tok", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    r = client.post(f"/api/approvals/{aid}/decide", headers={"X-EEZE-Token": "tok"},
                    json={"decision": "approve", "auto_resume": False,
                          "grant": {"scope": "agent", "ttl_hours": 24}})
    assert r.status_code == 200 and r.json()["grant_id"] is None and r.json()["grant_refused"]
    assert store.list_grants() == []
