"""`eeze open` one-time pairing codes, update freshness and the folder browser."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core import pairing
from eeze_agent.core.fsbrowse import list_dir

TOKEN = "synthetic-local-token-for-open"


def _app(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "api.db"))
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text(TOKEN, encoding="utf-8")
    return TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home)), home


def test_codes_are_single_use_and_expire(tmp_path):
    code = pairing.create_code(tmp_path, now=1000.0)
    assert code not in (tmp_path / "pair-codes.json").read_text()  # only the hash is stored
    assert pairing.consume_code(tmp_path, code, now=1001.0)
    assert not pairing.consume_code(tmp_path, code, now=1002.0)
    late = pairing.create_code(tmp_path, now=1000.0)
    assert not pairing.consume_code(tmp_path, late, now=1000.0 + pairing.CODE_TTL_S + 1)
    assert not pairing.consume_code(tmp_path, "short", now=1000.0)
    assert not pairing.consume_code(tmp_path, None, now=1000.0)  # type: ignore[arg-type]


def test_pair_with_code_sets_cookie_once(tmp_path, monkeypatch):
    client, home = _app(tmp_path, monkeypatch)
    assert client.get("/api/runs").status_code == 401
    code = pairing.create_code(home)
    response = client.post("/api/session/pair", json={"code": code})
    assert response.status_code == 200
    assert TOKEN not in response.text
    assert client.get("/api/runs").status_code == 200
    other = TestClient(client.app)
    assert other.post("/api/session/pair", json={"code": code}).status_code == 401
    assert other.post("/api/session/pair", json={"code": "x" * 40}).status_code == 401


def test_freshness_and_fs_list_need_pairing(tmp_path, monkeypatch):
    client, _home = _app(tmp_path, monkeypatch)
    assert client.get("/api/system/freshness").status_code == 401
    assert client.get("/api/fs/list").status_code == 401
    client.post("/api/session/pair", json={"token": TOKEN})
    fresh = client.get("/api/system/freshness").json()
    assert set(fresh) >= {"update_ready", "service_stale", "ui_stale"}
    assert isinstance(fresh["update_ready"], bool)
    folder = tmp_path / "pics"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.jpg").write_bytes(b"x")
    listing = client.get("/api/fs/list", params={"path": str(folder), "files": "true"}).json()
    assert listing["dirs"] == ["sub"] and listing["media_count"] == 1
    assert listing["files"][0]["name"] == "a.jpg"
    assert client.get("/api/fs/list", params={"path": str(folder / "nope")}).status_code == 404
    assert client.get("/api/fs/list", params={"path": str(folder / "a.jpg")}).status_code == 404


def test_list_dir_skips_hidden_and_counts_media(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "Trips").mkdir()
    (tmp_path / "$RECYCLE.BIN").mkdir()
    (tmp_path / "desktop.ini").write_text("x")
    (tmp_path / "clip.MP4").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    out = list_dir(str(tmp_path), home=tmp_path)
    assert out["dirs"] == ["Trips"]
    assert out["media_count"] == 1 and out["files"] == []
    assert out["parent"] == str(tmp_path.resolve().parent)
    assert out["places"][0] == {"label": "Home", "path": str(tmp_path)}
    quoted = list_dir(f'"{tmp_path}"', include_files=True, home=tmp_path)
    assert [f["name"] for f in quoted["files"]] == ["clip.MP4"]


def test_cli_open_prints_paired_url(tmp_path, monkeypatch, capsys):
    from eeze_agent.api import daemon
    from eeze_agent.cli import main

    monkeypatch.setattr(daemon, "HOME", tmp_path)
    monkeypatch.setattr(daemon, "http_up", lambda port: True)
    started = []
    monkeypatch.setattr(daemon, "start", lambda **kw: started.append(kw))
    assert main(["open", "/setup", "--print-only"]) == 0
    url = capsys.readouterr().out.strip()
    assert url.startswith("http://127.0.0.1:8765/pair?next=/setup#code=")
    code = url.split("#code=", 1)[1]
    assert not started
    assert pairing.consume_code(tmp_path, code)
    assert os.path.exists(tmp_path / "pair-codes.json")


def test_unpair_signs_every_browser_out(tmp_path, monkeypatch, capsys):
    from eeze_agent.api import daemon
    from eeze_agent.cli import main

    client, home = _app(tmp_path, monkeypatch)
    client.post("/api/session/pair", json={"token": TOKEN})
    assert client.get("/api/runs").status_code == 200
    monkeypatch.setattr(daemon, "HOME", home)
    assert main(["unpair"]) == 0
    assert (home / "api.token").read_text().strip() != TOKEN
    assert client.get("/api/runs").status_code == 401


def test_session_lasts_configured_days(tmp_path, monkeypatch):
    monkeypatch.setenv("EEZE_SESSION_DAYS", "2")
    client, _home = _app(tmp_path, monkeypatch)
    response = client.post("/api/session/pair", json={"token": TOKEN})
    assert "Max-Age=172800" in response.headers["set-cookie"]
