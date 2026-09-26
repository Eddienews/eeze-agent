"""v2 — user-level agents: registry merge + create/delete API (token-gated)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.agents.registry import AgentRegistry
from eeze_agent.api.app import create_app

TOKEN = {"X-EEZE-Token": "test-token-123"}

REPO_YAML = """\
agents:
  - id: default
    name: Default
  - id: ops
    name: Ops
    permissions:
      risk_classes: [read]
"""


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "agents.yaml").write_text(REPO_YAML, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "api.token").write_text(TOKEN["X-EEZE-Token"], encoding="utf-8")
    app = create_app(repo_root=repo, serve_ui=False, eeze_home=home)
    client = TestClient(app)
    assert client.post("/api/session/pair", json={"token": TOKEN["X-EEZE-Token"]}).status_code == 200
    return client


def test_registry_merges_user_overrides(tmp_path: Path):
    repo = tmp_path / "agents.yaml"
    repo.write_text(REPO_YAML, encoding="utf-8")
    user = tmp_path / "user-agents.yaml"
    user.write_text(
        "agents:\n  - id: ops\n    name: Ops (custom)\n  - id: scout\n    name: Scout\n",
        encoding="utf-8",
    )
    registry = AgentRegistry.from_sources(repo, user)
    ids = registry.ids()
    assert ids == ["default", "ops", "scout"]
    assert registry.get("ops").name == "Ops (custom)"  # user overrides repo
    assert registry.get("scout").name == "Scout"  # user adds new


def test_create_agent_requires_token_and_validates(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = {
        "id": "scout",
        "name": "Scout",
        "role": "research",
        "permissions": {"risk_classes": ["read"], "apps": ["*"], "allow_foreground": False},
        "model": {"brain": "llm"},
    }
    assert client.post("/api/agents", json=body).status_code == 401
    assert client.post("/api/agents", json={**body, "id": "Bad Slug!"}, headers=TOKEN).status_code == 422
    assert (
        client.post("/api/agents", json={**body, "model": {"brain": "gpt9"}}, headers=TOKEN).status_code
        == 422
    )
    assert (
        client.post(
            "/api/agents",
            json={**body, "permissions": {"risk_classes": ["teleport"]}},
            headers=TOKEN,
        ).status_code
        == 422
    )


def test_create_and_delete_user_agent_round_trip(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = {
        "id": "scout",
        "name": "Scout",
        "role": "research",
        "permissions": {"risk_classes": ["read"], "apps": ["*"], "allow_foreground": False},
        "model": {"brain": "llm"},
    }
    created = client.post("/api/agents", json=body, headers=TOKEN)
    assert created.status_code == 200
    assert created.json()["id"] == "scout" and created.json()["role"] == "research"
    assert created.json()["source"] == "user"

    user_file = tmp_path / "home" / "agents.yaml"
    assert user_file.exists() and "scout" in user_file.read_text(encoding="utf-8")

    listing = client.get("/api/agents").json()
    ids = [a["id"] for a in listing["items"]]
    assert "scout" in ids and "ops" in ids and "default" in ids  # merged view

    # user can update by re-posting the same id
    updated = client.post("/api/agents", json={**body, "name": "Scout v2"}, headers=TOKEN).json()
    assert updated["name"] == "Scout v2"
    assert user_file.read_text(encoding="utf-8").count("id: scout") == 1

    assert client.delete("/api/agents/scout", headers=TOKEN).status_code == 200
    assert "scout" not in [a["id"] for a in client.get("/api/agents").json()["items"]]
    assert client.delete("/api/agents/scout", headers=TOKEN).status_code == 404
    # repo-level agents are not deletable via this endpoint
    assert client.delete("/api/agents/finance", headers=TOKEN).status_code == 404


def test_user_agent_gets_its_own_brain(tmp_path: Path, monkeypatch):
    # aligned home: eeze_home == Path.home()/".eeze" so load_registry finds the file
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    monkeypatch.delenv("EEZE_BRAIN", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "agents.yaml").write_text(REPO_YAML, encoding="utf-8")
    home = tmp_path / ".eeze"
    home.mkdir(parents=True, exist_ok=True)
    (home / "api.token").write_text(TOKEN["X-EEZE-Token"], encoding="utf-8")
    client = TestClient(create_app(repo_root=repo, serve_ui=False, eeze_home=home))

    body = {
        "id": "scout",
        "name": "Scout",
        "permissions": {"risk_classes": ["read"]},
        "model": {"brain": "llm"},
    }
    assert client.post("/api/agents", json=body, headers=TOKEN).status_code == 200

    from eeze_agent.brains.llm import LlmBrain
    from eeze_agent.brains.registry import make_brain

    brain = make_brain(agent_id="scout", repo_root=repo)
    assert isinstance(brain, LlmBrain)  # brain comes from the user-level yaml


def test_update_agent_is_an_upsert_with_description(tmp_path: Path, monkeypatch):
    """POST with an existing id updates in place (no duplicate entries) incl. description."""
    import yaml

    client = _client(tmp_path, monkeypatch)
    first = {
        "id": "scout",
        "name": "Scout",
        "role": "research",
        "description": "Tracks sources.",
        "permissions": {"risk_classes": ["read", "write_local"]},
        "model": {"brain": "llm"},
    }
    assert client.post("/api/agents", json=first, headers=TOKEN).status_code == 200

    second = {**first, "name": "Scout II", "description": "Now sharper."}
    updated = client.post("/api/agents", json=second, headers=TOKEN)
    assert updated.status_code == 200
    assert updated.json()["name"] == "Scout II"
    assert updated.json()["description"] == "Now sharper."
    assert updated.json()["model"]["brain"] == "llm"  # real brain, not the schema default

    data = yaml.safe_load((tmp_path / "home" / "agents.yaml").read_text(encoding="utf-8"))
    scouts = [a for a in data["agents"] if a.get("id") == "scout"]
    assert len(scouts) == 1  # upsert, not append
    assert scouts[0]["name"] == "Scout II" and scouts[0]["description"] == "Now sharper."

    got = client.get("/api/agents/scout")
    assert got.status_code == 200 and got.json()["description"] == "Now sharper."
