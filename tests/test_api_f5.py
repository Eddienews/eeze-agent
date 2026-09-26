"""F5 — routines + setup endpoints: CRUD, token gate, run spawn, .env write, probe."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core.envfile import read_env, update_env
from eeze_agent.core.routines import RoutineStore
from eeze_agent.core.settings import SettingsStore

TOKEN = {"X-EEZE-Token": "test-token-123"}


def _client(tmp_path: Path, monkeypatch, *, spawned: list | None = None) -> TestClient:
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "api.token").write_text(TOKEN["X-EEZE-Token"], encoding="utf-8")
    if spawned is not None:
        import eeze_agent.core.routines as routines_mod

        monkeypatch.setattr(
            routines_mod,
            "spawn_detached",
            lambda argv, cwd, log_path: spawned.append(list(argv)),
        )
    app = create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home)
    client = TestClient(app)
    assert client.post("/api/session/pair", json={"token": TOKEN["X-EEZE-Token"]}).status_code == 200
    return client


# ---------------- envfile unit ----------------

def test_envfile_roundtrip_preserves_comments_and_order(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("# header\nA=1\n# note\nB=old value\n", encoding="utf-8")
    update_env(env, {"B": "new", "C": "has space"})
    text = env.read_text(encoding="utf-8")
    assert text.startswith("# header\nA=1\n# note\nB=new\n")
    assert 'C="has space"' in text
    parsed = read_env(env)
    assert parsed["A"] == "1" and parsed["B"] == "new" and parsed["C"] == "has space"
    # idempotent: second update only touches the given key
    update_env(env, {"A": "2"})
    assert read_env(env)["B"] == "new"


def test_settings_store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    store = SettingsStore()
    assert store.get_bool("setup_done") is False
    store.set("setup_done", "1")
    assert store.get_bool("setup_done") is True
    store.delete("setup_done")
    assert store.get("setup_done") is None


# ---------------- routines endpoints ----------------

def test_routines_crud_and_gates(tmp_path: Path, monkeypatch):
    spawned: list = []
    client = _client(tmp_path, monkeypatch, spawned=spawned)
    body = {
        "id": "inv1",
        "name": "Faturas",
        "kind": "invoices",
        "schedule": {"type": "daily", "at": "08:00"},
        "params": {"email_summary": True, "email_to": "a@b.co"},
    }
    assert client.post("/api/routines", json=body).status_code == 401

    created = client.post("/api/routines", json=body, headers=TOKEN)
    assert created.status_code == 200
    row = created.json()
    assert row["id"] == "inv1" and row["next_run_at"] and row["params"]["email_summary"] is True

    listing = client.get("/api/routines").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == "inv1"

    bad = client.post(
        "/api/routines",
        json={**body, "id": "bad1", "schedule": {"type": "daily", "at": "8h"}},
        headers=TOKEN,
    )
    assert bad.status_code == 422

    assert (
        client.post("/api/routines/inv1/enable", json={"enabled": False}, headers=TOKEN).json()["enabled"]
        is False
    )
    assert client.post("/api/routines/nope/enable", json={"enabled": True}, headers=TOKEN).status_code == 404

    ran = client.post("/api/routines/inv1/run", headers=TOKEN)
    assert ran.status_code == 200 and ran.json()["spawned"] is True
    assert spawned == [["routines", "run", "inv1"]]

    runs = client.get("/api/routines/inv1/runs").json()
    assert runs["total"] == 0  # run was spawned detached, not executed here
    assert client.get("/api/routines/nope/runs").status_code == 404

    assert client.delete("/api/routines/inv1", headers=TOKEN).status_code == 200
    assert client.get("/api/routines").json()["total"] == 0


def test_routine_create_task_kind_and_update_in_place(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch, spawned=[])
    body = {
        "id": "demo",
        "kind": "task",
        "schedule": {"type": "every", "minutes": 15},
        "params": {"task_path": "tasks/notepad-gated-demo.yaml"},
        "agent_id": "finance",
    }
    assert client.post("/api/routines", json=body, headers=TOKEN).status_code == 200
    # re-add with the same id updates in place
    updated = client.post(
        "/api/routines",
        json={**body, "schedule": {"type": "every", "minutes": 30}},
        headers=TOKEN,
    ).json()
    assert updated["schedule"]["minutes"] == 30
    assert updated["agent_id"] == "finance"
    assert client.get("/api/routines").json()["total"] == 1


# ---------------- setup endpoints ----------------

def test_setup_state_and_complete(tmp_path: Path, monkeypatch):
    RoutineStore()  # create db tables first (client also does)
    client = _client(tmp_path, monkeypatch, spawned=[])
    state = client.get("/api/setup/state").json()
    assert state["needs_setup"] is True
    assert state["imap_configured"] is False
    assert state["version"].startswith("0.1.0")

    assert client.post("/api/setup/complete").status_code == 401
    assert client.post("/api/setup/complete", headers=TOKEN).status_code == 200
    assert client.get("/api/setup/state").json()["needs_setup"] is False


def test_setup_imap_writes_env_never_echoes_password(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch, spawned=[])
    payload = {"host": "imap.gmail.com", "user": "u@example.com", "app_password": "abcd efgh ijkl mnop"}
    assert client.post("/api/setup/imap", json=payload).status_code == 401
    ok = client.post("/api/setup/imap", json=payload, headers=TOKEN)
    assert ok.status_code == 200
    assert "app_password" not in ok.text and "abcd" not in ok.text  # value never echoed
    env = read_env(tmp_path / ".env")
    assert env["EEZE_IMAP_USER"] == "u@example.com"
    assert env["EEZE_IMAP_APP_PASSWORD"] == "abcd efgh ijkl mnop"
    state = client.get("/api/setup/state").json()
    assert state["imap_configured"] is True and state["imap_user"] == "u@example.com"


def test_setup_imap_test_uses_probe(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch, spawned=[])
    import eeze_agent.verticals.invoices.imap_source as imap_mod

    calls: list = []

    def fake_test_login(host, user, password, folder="INBOX"):
        calls.append((host, user, password))
        return {"host": host, "folder": folder, "messages": 7}

    monkeypatch.setattr(imap_mod, "test_login", fake_test_login)
    payload = {"host": "imap.gmail.com", "user": "u@example.com", "app_password": "pw12345678"}
    result = client.post("/api/setup/imap/test", json=payload, headers=TOKEN).json()
    assert result == {"ok": True, "host": "imap.gmail.com", "folder": "INBOX", "messages": 7}
    assert calls == [("imap.gmail.com", "u@example.com", "pw12345678")]

    def boom(*_a, **_k):
        raise imap_mod.ImapError("AUTHENTICATIONFAILED: bad password")

    monkeypatch.setattr(imap_mod, "test_login", boom)
    failed = client.post("/api/setup/imap/test", json=payload, headers=TOKEN).json()
    assert failed["ok"] is False and "AUTHENTICATIONFAILED" in failed["error"]


def test_system_info_paths_keys_and_counts(tmp_path: Path, monkeypatch):
    """Read-only runtime facts for the Settings page — presence of keys, no values."""
    client = _client(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text(
        "TYPESAFE_API_KEY=fake-1\nEEZE_EXTRACT_API_KEY=fake-2\n", encoding="utf-8"
    )
    for name in ("rs-a", "rs-b"):
        (tmp_path / "artifacts" / "runs" / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "backups").mkdir(exist_ok=True)
    (tmp_path / "backups" / "eeze-backup-x.zip").write_bytes(b"PK")

    info = client.get("/api/system/info").json()
    assert info["keys"]["typesafe"] is True
    assert info["keys"]["extract"] is True
    assert info["keys"]["brain"] is False  # no EEZE_BRAIN_*/EEZE_PLANNER_* in this .env
    assert info["keys"]["imap"] is False
    assert info["runsets"] == 2 and info["backups"] == 1
    assert info["store_path"].endswith("api.db")
    assert info["token_path"].endswith("api.token")
    assert info["user_agents_path"].endswith("agents.yaml")
    assert info["repo_agents_path"].endswith("agents.yaml")
    assert info["python"] and info["version"]
    assert info["api_pid"] > 0  # answered by the server process itself
    assert "secret" not in str(info).lower()
