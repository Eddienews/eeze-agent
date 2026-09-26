"""A3: operator pairing and private local API/artifact boundary."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core.approvals import ApprovalStore

TOKEN = "a3-synthetic-operator-token"
MARKER = "SYNTHETIC_SECRET_MARKER_A3"


def _app(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "a3.db"))
    artifact = tmp_path / "artifacts" / "runs" / "private" / "summary.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(MARKER, encoding="utf-8")
    return create_app(repo_root=tmp_path, eeze_home=home, serve_ui=False)


def test_unauthenticated_allowed_origin_cannot_read_token_or_private_data(tmp_path, monkeypatch):
    monkeypatch.setenv("EEZE_DEV_ORIGINS", "1")
    client = TestClient(_app(tmp_path, monkeypatch))
    origin = "http://localhost:5173"
    assert client.get("/api/health").json() == {"service": "eeze", "status": "ok"}
    token = client.get("/api/session/token", headers={"Origin": origin})
    assert token.status_code in {404, 410}
    assert TOKEN not in token.text
    for path in ("/api/approvals", "/api/runs", "/artifacts/runs/private/summary.json"):
        response = client.get(path, headers={"Origin": origin})
        assert response.status_code == 401
        assert response.headers.get("access-control-allow-origin") == origin
        assert MARKER not in response.text and TOKEN not in response.text


def test_pairing_requires_real_local_secret_and_issues_private_cookie(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.post("/api/session/pair", json={"token": "wrong"}).status_code == 401
    assert client.get("/api/runs", headers={"X-EEZE-Token": "wrong"}).status_code == 401
    response = client.post("/api/session/pair", json={"token": TOKEN})
    assert response.status_code == 200
    assert TOKEN not in response.text
    cookie = response.headers.get("set-cookie", "").lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/runs").status_code == 200
    assert client.get("/artifacts/runs/private/summary.json").text == MARKER
    # Existing CLI header flow remains valid without a browser cookie.
    standalone = TestClient(app)
    assert standalone.get("/api/runs", headers={"X-EEZE-Token": TOKEN}).status_code == 200


def test_fresh_local_app_creates_out_of_band_operator_token(tmp_path):
    home = tmp_path / "fresh-home"
    assert not (home / "api.token").exists()
    create_app(repo_root=tmp_path, eeze_home=home, serve_ui=False)
    assert (home / "api.token").is_file()
    assert len((home / "api.token").read_text(encoding="utf-8")) >= 32


def test_daemon_readiness_uses_minimal_health_not_private_status(monkeypatch):
    from eeze_agent.api import daemon

    paths = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"service": "eeze", "status": "ok"}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url):
            paths.append(url)
            return FakeResponse()

    monkeypatch.setattr(daemon.httpx, "Client", FakeClient)
    assert daemon.http_up() is True
    assert paths == ["http://127.0.0.1:8765/api/health"]


def test_cookie_tampering_rotation_and_artifact_escape_fail_closed(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.post("/api/session/pair", json={"token": TOKEN}).status_code == 200
    assert client.get("/api/runs").status_code == 200
    original = client.cookies.get("eeze_operator")
    assert original
    client.cookies.set("eeze_operator", original[:-1] + ("0" if original[-1] != "0" else "1"))
    assert client.get("/api/runs").status_code == 401
    client.cookies.set("eeze_operator", original)
    escaped = client.get("/artifacts/%2e%2e/home/api.token")
    assert escaped.status_code in {400, 404}
    assert TOKEN not in escaped.text
    (tmp_path / "home" / "api.token").write_text("synthetic-rotated-token", encoding="utf-8")
    assert client.get("/api/runs").status_code == 401
    assert client.get("/artifacts/runs/private/summary.json").status_code == 401


def test_cross_origin_and_nonlocal_peers_cannot_pair_or_write(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    local = TestClient(app)
    assert local.post("/api/session/pair", json={"token": TOKEN},
                      headers={"Origin": "https://evil.example"}).status_code == 403
    assert local.post("/api/session/pair", json={"token": TOKEN},
                      headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 403
    remote = TestClient(app, client=("203.0.113.2", 1234))
    assert remote.post("/api/session/pair", json={"token": TOKEN}).status_code == 403
    assert remote.get("/api/runs", headers={"X-EEZE-Token": TOKEN}).status_code == 403
    assert remote.get("/artifacts/runs/private/summary.json",
                      headers={"X-EEZE-Token": TOKEN}).status_code == 403
    store = ApprovalStore(tmp_path / "a3.db")
    approval_id = store.request(
        runset_id="rs", task="synthetic", task_path="", agent_id="default", run_index=1,
        step_id="step", step_index=0, action="click", risk_class="install_exec",
        reason="fixture", payload={}, action_digest="c" * 64,
    )
    store.save_run_state(approval_id, {"approval_id": approval_id})
    url = f"/api/approvals/{approval_id}/decide"
    decision = {"decision": "approve", "auto_resume": False}
    assert remote.post(url, json=decision, headers={"X-EEZE-Token": TOKEN}).status_code == 403
    assert local.post(url, json=decision, headers={"Origin": "https://evil.example",
                                                   "X-EEZE-Token": TOKEN}).status_code == 403
    assert store.get(approval_id)["status"] == "pending"
    assert local.post("/api/session/pair", json={"token": TOKEN}).status_code == 200
    assert local.post(url, json=decision).status_code == 401
    assert local.post(url, json=decision,
                      headers={"Origin": "http://testserver"}).status_code == 200
    assert store.get(approval_id)["status"] == "approved"
