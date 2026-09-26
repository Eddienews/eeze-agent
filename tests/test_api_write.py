"""F2/M1 — write endpoints: token gate, decide, grants (local-only, no process spawn)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core.approvals import ApprovalStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    token = "test-token-123"
    (home / "api.token").write_text(token, encoding="utf-8")
    app = create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home)
    client = TestClient(app)
    assert client.post("/api/session/pair", json={"token": token}).status_code == 200
    return client, home


def _seed_approval(tmp_path: Path, monkeypatch, *, bound: bool = False) -> tuple[ApprovalStore, str]:
    db = tmp_path / "api.db"
    monkeypatch.setenv("EEZE_DB", str(db))
    store = ApprovalStore(db)
    approval_id = store.request(
        runset_id="rs-api", task="api-task", task_path="", agent_id="default", run_index=1,
        step_id="install-1", step_index=1, action="invoke_menu", risk_class="install_exec",
        reason="heuristic install_exec", payload={"action": "invoke_menu"},
        action_digest="a" * 64 if bound else None,
    )
    store.save_run_state(approval_id, {"approval_id": approval_id})
    return store, approval_id


def test_approvals_listing_from_store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    _store, approval_id = _seed_approval(tmp_path, monkeypatch)
    client, _ = _client(tmp_path)
    body = client.get("/api/approvals").json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == approval_id
    assert item["risk_class"] == "install_exec"
    assert item["run_id"] == "rs-api.1"
    pending = client.get("/api/approvals", params={"status": "pending"}).json()
    assert pending["total"] == 1


def test_decide_requires_token(tmp_path: Path, monkeypatch):
    _store, approval_id = _seed_approval(tmp_path, monkeypatch)
    client, _ = _client(tmp_path)
    url = f"/api/approvals/{approval_id}/decide"
    assert client.post(url, json={"decision": "approve", "auto_resume": False}).status_code == 401
    assert (
        client.post(
            url, json={"decision": "approve", "auto_resume": False},
            headers={"X-EEZE-Token": "wrong"},
        ).status_code
        == 401
    )


def test_decide_refused_behind_proxy(tmp_path: Path, monkeypatch):
    _store, approval_id = _seed_approval(tmp_path, monkeypatch)
    client, _ = _client(tmp_path)
    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "approve", "auto_resume": False},
        headers={"X-EEZE-Token": "test-token-123", "X-Forwarded-For": "203.0.113.5"},
    )
    assert resp.status_code == 403


def test_decide_approve_and_deny_flow(tmp_path: Path, monkeypatch):
    _store, approval_id = _seed_approval(tmp_path, monkeypatch, bound=True)
    client, _ = _client(tmp_path)
    url = f"/api/approvals/{approval_id}/decide"
    headers = {"X-EEZE-Token": "test-token-123"}

    resp = client.post(url, json={"decision": "approve", "auto_resume": False}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["approval"]["status"] == "approved"
    assert body["resumed"] is False  # auto_resume disabled in test
    # second decision on a decided approval -> 409
    again = client.post(url, json={"decision": "deny", "auto_resume": False}, headers=headers)
    assert again.status_code == 409

    # deny path on a fresh approval
    second = _store.request(
        runset_id="rs-api", task="api-task", task_path="", agent_id="default", run_index=1,
        step_id="del-1", step_index=2, action="click", risk_class="destructive", reason="x",
        payload={}, action_digest="b" * 64,
    )
    _store.save_run_state(second, {"approval_id": second})
    resp2 = client.post(
        f"/api/approvals/{second}/decide",
        json={"decision": "deny", "auto_resume": False, "reason": "not today"},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["approval"]["status"] == "denied"


def test_grants_create_list_revoke(tmp_path: Path, monkeypatch):
    _store, approval_id = _seed_approval(tmp_path, monkeypatch, bound=True)
    client, _ = _client(tmp_path)
    headers = {"X-EEZE-Token": "test-token-123"}

    resp = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={
            "decision": "approve",
            "auto_resume": False,
            "grant": {"scope": "task", "ttl_hours": 24},
        },
        headers=headers,
    )
    assert resp.status_code == 200
    grant_id = resp.json()["grant_id"]
    assert grant_id

    grants = client.get("/api/grants").json()
    assert grants["total"] == 1
    grant = grants["items"][0]
    assert grant["id"] == grant_id and grant["scope"] == "task"
    assert grant["task"] == "api-task" and grant["status"] == "active"
    assert grant["expires_at"]

    # revoke needs the token too
    assert client.delete(f"/api/grants/{grant_id}").status_code == 401
    revoked = client.delete(f"/api/grants/{grant_id}", headers=headers)
    assert revoked.status_code == 200
    assert client.get("/api/grants").json()["total"] == 0
    assert client.get("/api/grants", params={"include_revoked": True}).json()["total"] == 1


def test_legacy_pending_cannot_be_decided_or_granted(tmp_path: Path, monkeypatch):
    store, approval_id = _seed_approval(tmp_path, monkeypatch)
    client, _ = _client(tmp_path)
    row = client.get("/api/approvals", params={"status": "pending"}).json()["items"][0]
    assert row["id"] == approval_id and row["resumable"] is False
    for decision in ("approve", "deny"):
        response = client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": decision, "grant": {"scope": "task"}, "auto_resume": True},
            headers={"X-EEZE-Token": "test-token-123"},
        )
        assert response.status_code == 409
        assert store.get(approval_id)["status"] == "pending"
        assert store.run_state_for(approval_id)["status"] == "waiting"
        assert store.count("pending") == 1
        assert store.list_grants() == []


def test_bound_approval_without_waiting_state_is_not_actionable(tmp_path: Path, monkeypatch):
    store, approval_id = _seed_approval(tmp_path, monkeypatch, bound=True)
    state = store.run_state_for(approval_id)
    store.set_run_state_status(state["id"], "superseded")
    client, _ = _client(tmp_path)
    row = client.get("/api/approvals").json()["items"][0]
    assert row["resumable"] is False
    response = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"decision": "approve", "grant": {"scope": "agent"}},
        headers={"X-EEZE-Token": "test-token-123"},
    )
    assert response.status_code == 409
    assert store.get(approval_id)["status"] == "pending"
    assert store.list_grants() == []


def test_bound_waiting_approval_is_actionable(tmp_path: Path, monkeypatch):
    _store, approval_id = _seed_approval(tmp_path, monkeypatch, bound=True)
    client, _ = _client(tmp_path)
    row = client.get("/api/approvals").json()["items"][0]
    assert row["id"] == approval_id and row["resumable"] is True


def test_system_status_has_pending_count(tmp_path: Path, monkeypatch):
    _seed_approval(tmp_path, monkeypatch)
    client, _ = _client(tmp_path)
    body = client.get("/api/system/status").json()
    assert body["pending_approvals"] == 1
