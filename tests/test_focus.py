"""F5/M4 — focus audit: sampler, analysis, artifact (no GUI needed)."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

from eeze_agent.core.focus import FocusSampler, Sample, analyze, run_focus_audit


def _stable(n: int, hwnd: int = 7, x: int = 100, y: int = 200) -> list[Sample]:
    return [Sample(t_ms=i * 200, hwnd=hwnd, title="Notepad", x=x, y=y) for i in range(n)]


def test_analyze_pass_on_stable_samples():
    report = analyze(_stable(5))
    assert report["pass"] is True
    assert report["focus_pass"] and report["cursor_pass"]
    assert report["focus_change_count"] == 0 and report["cursor_move_count"] == 0
    assert report["baseline"]["hwnd"] == 7


def test_analyze_fails_on_focus_change_and_cursor_move():
    samples = _stable(4)
    samples[2].hwnd = 9
    samples[2].title = "Other app"
    samples[3].x = 140
    report = analyze(samples)
    assert report["pass"] is False
    assert report["focus_change_count"] == 1
    assert report["cursor_move_count"] == 1
    assert report["cursor_max_delta"]["dx"] == 40


def test_analyze_empty_samples_fail_closed():
    report = analyze([])
    assert report["pass"] is False and report["samples"] == 0


def test_sampler_collects_with_injected_probe():
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return (7, "Notepad", 100, 200)

    sampler = FocusSampler(interval_s=0.01, probe=probe)
    sampler.start()
    time.sleep(0.08)
    sampler.stop()
    assert len(sampler.samples) >= 2
    assert calls["n"] == len(sampler.samples)
    assert all(s.hwnd == 7 for s in sampler.samples)


def test_run_focus_audit_writes_artifact(tmp_path: Path, monkeypatch):
    import eeze_agent.brains.jev as jev_mod
    import eeze_agent.core.loop as loop_mod
    import eeze_agent.core.tasks as tasks_mod
    import eeze_agent.drivers.cua as cua_mod

    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(Path(__file__).resolve().parents[1] / "agents.yaml", repo / "agents.yaml")
    task_path = repo / "task.yaml"
    task_path.write_text("name: t\nsteps: []\n", encoding="utf-8")

    monkeypatch.setattr(tasks_mod, "load_task", lambda path: SimpleNamespace(name="t"))
    monkeypatch.setattr(loop_mod, "run_set", lambda **kw: {"status": "done", "success_rate": "1/1"})

    class Dummy:
        def __init__(self):
            pass

    monkeypatch.setattr(cua_mod, "CuaDriver", Dummy)
    monkeypatch.setattr(jev_mod, "JevBrain", Dummy)

    sampler = FocusSampler(interval_s=0.01, probe=lambda: (7, "Notepad", 100, 200))
    result = run_focus_audit(task_path=task_path, repo_root=repo, runs=1, sampler=sampler)

    assert result["pass"] is True
    assert result["run_status"] == "done" and result["success_rate"] == "1/1"
    artifact = Path(result["artifact"])
    assert artifact.exists()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["pass"] is True and payload["task_name"] == "t"
    assert payload["focus_change_count"] == 0
