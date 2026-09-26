"""Fase 1 — security fixes: each test is the exploit that used to work."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.core.envfile import read_env, update_env
from eeze_agent.verticals.invoices.imap_source import ImapConfigError, validate_search

TOKEN = "tok-sec-1"
H = {"X-EEZE-Token": TOKEN}


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "e.db"))
    monkeypatch.setenv("EEZE_SECRETS", str(tmp_path / "secrets.json"))
    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text(TOKEN, encoding="utf-8")
    return TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))


# ---- .env newline injection -------------------------------------------------------------

def test_env_refuses_line_breaks(tmp_path: Path):
    env = tmp_path / ".env"
    with pytest.raises(ValueError):
        update_env(env, {"EEZE_IMAP_USER": "me@x.com\nEEZE_CODEX_BIN=calc.exe"})
    assert not env.exists() or "EEZE_CODEX_BIN" not in env.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        update_env(env, {"BAD KEY": "x"})


def test_env_round_trips_quotes_and_backslashes(tmp_path: Path):
    env = tmp_path / ".env"
    update_env(env, {"P": 'ab"cd ef\\gh'})
    assert read_env(env)["P"] == 'ab"cd ef\\gh'


def test_setup_imap_validates_user_and_host(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    bad_user = client.post("/api/setup/imap", headers=H, json={
        "host": "imap.gmail.com", "user": "me@x.com\nEEZE_BRAIN_BASE_URL=https://evil",
        "app_password": "abcd"})
    assert bad_user.status_code == 422
    bad_host = client.post("/api/setup/imap", headers=H, json={
        "host": "imap.gmail.com;rm", "user": "me@x.com", "app_password": "abcd"})
    assert bad_host.status_code == 422


# ---- IMAP search injection ----------------------------------------------------------------

@pytest.mark.parametrize("search", [
    "ALL\r\nA1 STORE 1:* +FLAGS (\\Deleted)", "ALL\nA2 EXPUNGE", "SUBJECT {5}", "ALL\x00",
])
def test_imap_search_refuses_injection(search: str):
    with pytest.raises(ImapConfigError):
        validate_search(search)


def test_imap_search_allows_normal_criteria():
    assert validate_search('SINCE 01-Sep-2026 SUBJECT "invoice"') == 'SINCE 01-Sep-2026 SUBJECT "invoice"'
    assert validate_search("") == "ALL"


def test_routine_api_rejects_injected_search_and_ungating(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    base = {"id": "inv", "kind": "invoices", "schedule": {"type": "daily", "at": "08:00"}}
    r = client.post("/api/routines", headers=H,
                    json={**base, "params": {"search": "ALL\r\nA1 EXPUNGE"}})
    assert r.status_code == 422
    r = client.post("/api/routines", headers=H, json={**base, "params": {
        "email_summary": True, "email_to": "outsider@example.com", "allow": ["external_send"]}})
    assert r.status_code == 422
    r = client.post("/api/routines", headers=H, json={**base, "params": {
        "email_to": "a@b.com\r\nBcc: x@y.com"}})
    assert r.status_code == 422
    ok = client.post("/api/routines", headers=H, json={**base, "params": {"allow": ["write_local"]}})
    assert ok.status_code == 200, ok.text


# ---- provider endpoint / model -----------------------------------------------------------

def test_provider_rejects_shell_metachar_models_and_plain_http(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.put("/api/providers/codex", headers=H,
                   json={"default_models": {"routine": "x&calc.exe"}})
    assert r.status_code == 422
    r = client.put("/api/providers/openai", headers=H, json={"base_url": "http://evil.example/v1"})
    assert r.status_code == 422
    r = client.put("/api/providers/ollama", headers=H, json={"base_url": "http://127.0.0.1:11434/v1"})
    assert r.status_code == 200, r.text


def test_saved_key_is_bound_to_its_host(tmp_path: Path, monkeypatch):
    from eeze_agent.core.providers import resolve_provider

    client = _client(tmp_path, monkeypatch)
    home = tmp_path / "home"
    assert client.post("/api/providers/openai/key", headers=H,
                       json={"key": "sk-test-0123456789abcdef"}).status_code == 200
    ok = resolve_provider("brain", provider_id="openai", home=home)
    assert ok.api_key == "sk-test-0123456789abcdef"
    client.put("/api/providers/openai", headers=H, json={"base_url": "https://evil.example/v1"})
    moved = resolve_provider("brain", provider_id="openai", home=home)
    assert moved.base_url.startswith("https://evil.example")
    assert moved.api_key != "sk-test-0123456789abcdef"
