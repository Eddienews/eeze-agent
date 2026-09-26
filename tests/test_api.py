"""Read-only API tests — contract slice against a tmp fixture "runset"."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app


def _fixture(root: Path) -> None:
    rs = root / "artifacts" / "runs" / "20260101-000000-demo"
    rs.mkdir(parents=True)
    events = [
        {"ts": "2026-01-01T00:00:00+00:00", "kind": "runset_start", "task": "demo",
         "agent_id": "default", "runs": 1},
        {"ts": "2026-01-01T00:00:01+00:00", "kind": "run_start", "run_index": 1,
         "agent_id": "default"},
        {"ts": "2026-01-01T00:00:02+00:00", "kind": "judgment", "run_index": 1, "step_id": "s1",
         "judgment_kind": "select_element", "question": "q", "answer": "c0",
         "confidence": 1.0, "ms": 10},
        {"ts": "2026-01-01T00:00:03+00:00", "kind": "step_end", "run_index": 1, "step_id": "s1",
         "ok": True, "attempts": 1, "ms": 5},
        {"ts": "2026-01-01T00:00:04+00:00", "kind": "run_end", "run_index": 1, "ok": True,
         "cycle_ms": 4000},
    ]
    (rs / "journal.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    (rs / "summary.json").write_text(
        json.dumps({"cost_estimate_usd": 0.001, "jev_calls": 2}), encoding="utf-8"
    )


def _client(tmp_path: Path) -> TestClient:
    _fixture(tmp_path)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "api.token").write_text("synthetic-local-token", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "synthetic-local-token"}).status_code == 200
    return client


def test_agents_lists_default(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/api/agents").json()
    assert [a["id"] for a in body["items"]] == ["default"]
    assert body["items"][0]["metrics"]["runs_total"] == 1
    assert body["items"][0]["metrics"]["success_rate"] == 1.0


def test_agent_detail_and_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/agents/default").status_code == 200
    r = client.get("/api/agents/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_runs_list_and_detail(tmp_path: Path) -> None:
    client = _client(tmp_path)
    runs = client.get("/api/runs").json()
    assert runs["total"] == 1
    assert runs["items"][0]["status"] == "ok"
    assert runs["items"][0]["id"] == "20260101-000000-demo.1"

    detail = client.get("/api/runs/20260101-000000-demo.1").json()
    assert detail["steps"][0]["ok"] is True
    assert detail["steps"][0]["judgment"]["answer"] == "c0"
    assert detail["journal_url"].endswith("journal.jsonl")

    assert client.get("/api/runs/20260101-000000-demo.9").status_code == 404
    assert client.get("/api/runs/garbage").status_code == 400


def test_runs_filters(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/runs", params={"status": "failed"}).json()["total"] == 0
    assert client.get("/api/runs", params={"interference": "true"}).json()["total"] == 0
    assert client.get("/api/runs", params={"task_name": "demo"}).json()["total"] == 1


def test_approvals_empty_contract(tmp_path: Path, monkeypatch) -> None:
    # isolate the approval store so the contract test is deterministic
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "isolated.db"))
    body = _client(tmp_path).get("/api/approvals").json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_system_status(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/api/system/status").json()
    assert "daemon" in body
    assert body["runs_total"] == 1
    assert body["agents"][0]["id"] == "default"


def test_cors_allowed_origins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EEZE_DEV_ORIGINS", "1")
    client = _client(tmp_path)
    for origin in ("http://localhost:5173", "http://localhost:3000"):
        r = client.get("/api/agents", headers={"Origin": origin})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == origin, origin


def test_cors_preflight(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EEZE_DEV_ORIGINS", "1")
    client = _client(tmp_path)
    r = client.options(
        "/api/runs",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_disallowed_origin_gets_no_header(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.get("/api/agents", headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_api_served_under_prefix_only(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/agents").status_code == 200
    assert client.get("/api/runs").json()["total"] == 1
    assert client.get("/api/system/status").json()["runs_total"] == 1


def test_ui_serving_with_spa_fallback(tmp_path: Path) -> None:
    _fixture(tmp_path)
    dist = tmp_path / "ui" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>EEZE_UI</body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('eeze')", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, eeze_home=tmp_path / "home"))

    root = client.get("/")
    assert root.status_code == 200
    assert "EEZE_UI" in root.text

    deep = client.get("/agents/default/runs/whatever")  # client-side route -> fallback
    assert deep.status_code == 200
    assert "EEZE_UI" in deep.text

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text

    api = client.get("/api/agents")  # API wins over the catch-all
    assert api.headers["content-type"].startswith("application/json")

    # regression: the root no longer aliases the API — client routes like a
    # hypothetical /approvals must reach the SPA, never the API.
    assert client.get("/approvals").status_code == 200  # SPA fallback
    assert not client.get("/approvals").headers["content-type"].startswith("application/json")


def test_ui_not_served_when_no_dist(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/").status_code == 404


def test_dev_origins_are_off_by_default(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = client.get("/api/agents", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 403
    assert '"openapi"' not in client.get("/openapi.json").text
    assert client.get("/docs").status_code != 200 or "swagger" not in client.get("/docs").text.lower()
