"""Watched folders: a Files mission starts itself when its folder changes (and only then)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from eeze_agent.core import watch
from eeze_agent.core.missions import MissionError, MissionStore, sync_schedule
from eeze_agent.core.routines import RoutineStore, Scheduler, compute_next_run


def _photos(folder: Path, names: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(name.encode())


def _mission(tmp_path: Path, monkeypatch, folder: Path) -> MissionStore:
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("EEZE_WATCH_SETTLE_S", "30")
    store = MissionStore(tmp_path)
    plan = f"name: tidy\nfolder: '{folder}'\nop: rename\npattern: trip{{n:03}}\n"
    store.save({"id": "tidy", "name": "Tidy", "kind": "files", "plan": plan,
                "sources": str(folder), "schedule": {"type": "watch"}})
    sync_schedule(store.get("tidy"), home=tmp_path)
    return store


def test_watch_schedule_has_no_clock_and_is_files_only(tmp_path, monkeypatch):
    assert compute_next_run({"type": "watch"}) is None
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    with pytest.raises(MissionError):
        MissionStore(tmp_path).save({"id": "v", "kind": "video", "schedule": {"type": "watch"}})


def test_fingerprint_ignores_hidden_and_waits_for_downloads(tmp_path):
    _photos(tmp_path, ["a.jpg"])
    first = watch.fingerprint(tmp_path)
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "sub").mkdir()
    assert watch.fingerprint(tmp_path) == first
    (tmp_path / "b.jpg.crdownload").write_text("x")
    assert watch.fingerprint(tmp_path) is None
    assert watch.fingerprint(tmp_path / "missing") is None


def test_evaluate_settles_then_proposes_once_and_ignores_its_own_result(tmp_path, monkeypatch):
    folder = tmp_path / "Pictures"
    _photos(folder, ["IMG_2.jpg", "IMG_1.jpg"])
    _mission(tmp_path, monkeypatch, folder)
    rid, t = "mission:tidy", 1_000.0
    assert watch.evaluate(tmp_path, rid, busy=False, now=t)["action"] == "wait"       # first sight
    assert watch.evaluate(tmp_path, rid, busy=False, now=t + 10)["action"] == "wait"  # settling
    assert watch.evaluate(tmp_path, rid, busy=True, now=t + 40)["action"] == "wait"   # run open
    result = watch.evaluate(tmp_path, rid, busy=False, now=t + 40)
    assert result["action"] == "run" and result["changes"] == 2
    watch.mark_triggered(tmp_path, rid, now=t + 40)
    assert watch.evaluate(tmp_path, rid, busy=False, now=t + 200)["action"] == "idle"  # same state
    # the approved run renames the files -> the folder changes -> nothing left to do
    os.rename(folder / "IMG_1.jpg", folder / "trip001.jpg")
    os.rename(folder / "IMG_2.jpg", folder / "trip002.jpg")
    assert watch.evaluate(tmp_path, rid, busy=False, now=t + 300)["action"] == "wait"
    done = watch.evaluate(tmp_path, rid, busy=False, now=t + 340)
    assert done == {"action": "idle", "detail": "nothing to do"}
    # a new photo arrives -> proposed again
    _photos(folder, ["IMG_9.jpg"])
    watch.evaluate(tmp_path, rid, busy=False, now=t + 400)
    again = watch.evaluate(tmp_path, rid, busy=False, now=t + 440)
    assert again["action"] == "run" and again["changes"] == 1  # IMG_9 -> trip003, the rest stay


def test_scheduler_spawns_watched_mission_once(tmp_path, monkeypatch):
    folder = tmp_path / "Downloads"
    _photos(folder, ["b.jpg", "a.jpg"])
    _mission(tmp_path, monkeypatch, folder)
    spawned: list[list[str]] = []
    sched = Scheduler(RoutineStore(), repo_root=tmp_path, home=tmp_path,
                      spawn=lambda argv, cwd, log_path: spawned.append(list(argv)))
    t0 = datetime.now()  # noqa: DTZ005
    assert sched.tick(now=t0) == []
    assert sched.tick(now=t0 + timedelta(seconds=45)) == ["mission:tidy"]
    assert spawned == [["routines", "run", "mission:tidy"]]
    assert sched.tick(now=t0 + timedelta(minutes=5)) == []  # nothing changed since
    row = RoutineStore().get("mission:tidy")
    assert row["next_run_at"] is None and row["last_status"] == "spawned"
    log = (tmp_path / "routines" / "run-mission-tidy.log").read_text(encoding="utf-8")
    assert "waiting for your approval" in log


def test_disabled_or_timed_routines_are_not_watched(tmp_path, monkeypatch):
    folder = tmp_path / "F"
    _photos(folder, ["x.jpg"])
    store = _mission(tmp_path, monkeypatch, folder)
    RoutineStore().set_enabled("mission:tidy", False)
    sched = Scheduler(RoutineStore(), repo_root=tmp_path, home=tmp_path,
                      spawn=lambda *a, **k: pytest.fail("must not spawn"))
    t0 = datetime.now()  # noqa: DTZ005
    sched.tick(now=t0)
    sched.tick(now=t0 + timedelta(minutes=2))
    assert store.get("tidy")["schedule"] == {"type": "watch"}


def test_keep_done_continues_the_count_without_renumbering(tmp_path):
    from eeze_agent.verticals.files.runner import plan_changes
    from eeze_agent.verticals.files.spec import FilesSpec

    _photos(tmp_path, ["trip001.jpg", "trip002.jpg", "IMG_9.jpg", "IMG_10.jpg"])
    base = dict(name="t", folder=str(tmp_path), op="rename", pattern="trip{n:03}")
    kept = plan_changes(FilesSpec(**base, keep_done=True))
    assert kept["kept"] == 2
    assert kept["changes"] == [{"from": "IMG_9.jpg", "to": "trip003.jpg"},
                               {"from": "IMG_10.jpg", "to": "trip004.jpg"}]
    # without it, the whole folder is renumbered (the original behaviour)
    assert len(plan_changes(FilesSpec(**base))["changes"]) == 4


def test_watched_rename_runs_with_keep_done(tmp_path, monkeypatch):
    from eeze_agent.core.missions import effective_plan, to_public

    folder = tmp_path / "P"
    _photos(folder, ["a.jpg"])
    store = _mission(tmp_path, monkeypatch, folder)
    row = store.get("tidy")
    assert "keep_done: true" in effective_plan(row) and "keep_done" not in row["plan"]
    assert "keep_done: true" in to_public(row, plan=True)["run_plan"]
