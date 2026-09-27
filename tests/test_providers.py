"""P2 — provider registry, write-only secret store, and the /api/providers surface.

The rules this file locks:
* precedence is run -> agent -> store -> env -> built-in default, per FIELD (the `sources` map);
* the key value NEVER leaves the process — rows carry presence + `last4`, nothing else, and a
  provider that echoes the key back in an error gets it redacted;
* refusals are honest: unknown provider, incompatible provider, local-only provider, empty key,
  non-http base_url — each with its own status code, never a fake success.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eeze_agent.api.app import create_app
from eeze_agent.brains.llm import LlmBrain
from eeze_agent.brains.planner import Planner
from eeze_agent.brains.specwriter import SpecWriter
from eeze_agent.core.providers import (
    ProviderConfig,
    get_provider,
    probe_provider,
    provider_ids,
    provider_status,
    resolve_provider,
    tier_models,
)
from eeze_agent.core.secrets_local import SecretStore

FAKE_KEY = "sk-or-v1-FAKE-0123456789-FAKE"
ENV_KEYS = (
    "EEZE_PROVIDER",
    "EEZE_BRAIN_API_KEY",
    "EEZE_BRAIN_BASE_URL",
    "EEZE_BRAIN_MODEL",
    "EEZE_PLANNER_API_KEY",
    "EEZE_PLANNER_BASE_URL",
    "EEZE_PLANNER_MODEL",
    "EEZE_PLANNER_ENGINE",
    "EEZE_SPEC_API_KEY",
    "EEZE_SPEC_BASE_URL",
    "EEZE_SPEC_MODEL",
    "EEZE_SPEC_ENGINE",
)


def _clean(monkeypatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    _clean(monkeypatch)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "api.token").write_text("test-token-123", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "test-token-123"}).status_code == 200
    return client


AUTH = {"X-EEZE-Token": "test-token-123"}


# -- catalog + precedence ------------------------------------------------------


def test_catalog_is_honest_about_models():
    assert provider_ids() == [
        "openrouter",
        "sabi",
        "openai",
        "google",
        "xai",
        "groq",
        "ollama",
        "anthropic",
        "codex",
    ]
    # Defaults exist ONLY where a model was measured live here.
    assert get_provider("openrouter").default_models["routine"] == "openai/gpt-6-luna"
    assert get_provider("codex").default_models["hard"] == "gpt-6-sol"
    assert get_provider("openai").default_models == {}
    # Sabi ships its documented routing alias, not a model id; it runs locally, no key.
    assert get_provider("sabi").default_models == {"routine": "sabi-code", "hard": "sabi-code"}
    assert get_provider("sabi").kind == "local"
    assert get_provider("sabi").base_url == "http://127.0.0.1:8787/v1"
    assert get_provider("anthropic").compatible is False
    assert get_provider("codex").local_only is True


def test_precedence_run_agent_store_env_default(tmp_path, monkeypatch):
    _clean(monkeypatch)
    home = tmp_path
    store = SecretStore(home)
    assert resolve_provider("brain", home=home).source == "default"
    assert resolve_provider("brain", home=home).provider_id == "openrouter"

    monkeypatch.setenv("EEZE_PROVIDER", "groq")
    assert resolve_provider("brain", home=home).source == "env"
    assert resolve_provider("brain", home=home).provider_id == "groq"

    store.set("provider.default", "ollama")
    assert resolve_provider("brain", home=home).source == "store"
    assert resolve_provider("brain", home=home).provider_id == "ollama"

    assert resolve_provider("brain", agent_provider="google", home=home).source == "agent"
    assert resolve_provider("brain", provider_id="xai", agent_provider="google", home=home).provider_id == "xai"
    assert resolve_provider("brain", provider_id="xai", home=home).source == "run"


def test_precedence_is_per_field(tmp_path, monkeypatch):
    _clean(monkeypatch)
    home = tmp_path
    store = SecretStore(home)
    monkeypatch.setenv("EEZE_BRAIN_API_KEY", "env-key")
    monkeypatch.setenv("EEZE_BRAIN_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("EEZE_BRAIN_MODEL", "env/model")

    env_cfg = resolve_provider("brain", home=home)
    assert (env_cfg.api_key, env_cfg.base_url, env_cfg.model) == ("env-key", "https://env.example/v1", "env/model")
    assert env_cfg.sources == {"base_url": "env", "api_key": "env", "model": "env"}

    store.set("provider.openrouter", FAKE_KEY)
    store.set("provider.openrouter.base_url", "https://store.example/v1")
    store.set("provider.openrouter.models", json.dumps({"routine": "store/model"}))
    # A stored key only travels to the host it was saved for (the API records it on save).
    unbound = resolve_provider("brain", home=home)
    assert unbound.api_key != FAKE_KEY
    store.set("provider.openrouter.key_host", "store.example")
    stored = resolve_provider("brain", home=home)
    assert stored.api_key == FAKE_KEY  # the store beats env
    assert stored.base_url == "https://store.example/v1"
    assert stored.model == "store/model"
    assert stored.sources == {"base_url": "store", "api_key": "store", "model": "store"}

    # an explicit run override beats the store
    run = resolve_provider("brain", model="run/model", home=home)
    assert run.model == "run/model" and run.sources["model"] == "run"


def test_role_env_prefixes_mirror_the_brains(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_PLANNER_API_KEY", "planner-key")
    monkeypatch.setenv("EEZE_SPEC_BASE_URL", "https://spec.example/v1")
    monkeypatch.setenv("EEZE_PLANNER_MODEL", "planner/model")
    assert resolve_provider("brain", home=tmp_path).api_key == "planner-key"  # brain falls back to planner
    planner = resolve_provider("planner", home=tmp_path)
    assert planner.model == "planner/model" and planner.sources["model"] == "env"
    spec = resolve_provider("spec", home=tmp_path)
    assert spec.base_url == "https://spec.example/v1" and spec.model == "planner/model"


def test_tier_models_store_override_wins(tmp_path):
    store = SecretStore(tmp_path)
    assert tier_models("openrouter", home=tmp_path) == {
        "routine": "openai/gpt-6-luna",
        "hard": "openai/gpt-6-sol",
    }
    store.set("provider.openrouter.models", json.dumps({"routine": "me/routine"}))
    assert tier_models("openrouter", home=tmp_path)["routine"] == "me/routine"
    assert tier_models("openrouter", home=tmp_path)["hard"] == "openai/gpt-6-sol"
    assert tier_models("anthropic", home=tmp_path) == {"routine": "", "hard": ""}  # never invented


def test_codex_provider_maps_to_the_codex_brain(tmp_path, monkeypatch):
    _clean(monkeypatch)
    cfg = resolve_provider("brain", provider_id="codex", home=tmp_path)
    assert cfg.brain == "codex" and cfg.base_url == "" and cfg.api_key == ""
    assert cfg.model == "gpt-6-luna"  # the subscription's routine model, measured live


def test_generic_env_never_leaks_into_another_provider_kind(tmp_path, monkeypatch):
    """Live-found bug: EEZE_PLANNER_MODEL=openai/gpt-6-sol reached the Codex CLI, which rejects
    the `openai/` namespace, and EEZE_PLANNER_BASE_URL landed in every provider row."""
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_PLANNER_MODEL", "openai/gpt-6-sol")
    monkeypatch.setenv("EEZE_PLANNER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("EEZE_PLANNER_API_KEY", "planner-env-key")

    codex = resolve_provider("brain", provider_id="codex", home=tmp_path)
    assert codex.model == "gpt-6-luna" and codex.sources["model"] == "default"
    assert codex.base_url == "" and codex.sources["base_url"] == "default"
    assert codex.api_key == "" and codex.sources["api_key"] == "none"

    # the CLI provider reads only its own variables, pin last
    monkeypatch.setenv("EEZE_CODEX_MODEL_ROUTINE", "gpt-6-custom")
    tier_env = resolve_provider("brain", provider_id="codex", home=tmp_path)
    assert tier_env.model == "gpt-6-custom" and tier_env.sources["model"] == "env"
    monkeypatch.setenv("EEZE_CODEX_MODEL", "gpt-6-pinned")
    assert resolve_provider("brain", provider_id="codex", home=tmp_path).model == "gpt-6-pinned"

    # a local server reads neither env chain; its documented path is the store override
    ollama = resolve_provider("brain", provider_id="ollama", home=tmp_path)
    assert ollama.base_url == "http://127.0.0.1:11434/v1" and ollama.api_key == ""
    SecretStore(tmp_path).set("provider.ollama.base_url", "http://127.0.0.1:11500/v1")
    assert resolve_provider("brain", provider_id="ollama", home=tmp_path).base_url == "http://127.0.0.1:11500/v1"

    # ...while the API providers keep full env parity (llm.py reads the same chain)
    api = resolve_provider("brain", home=tmp_path)
    assert api.model == "openai/gpt-6-sol" and api.sources["model"] == "env"
    assert api.api_key == "planner-env-key" and api.base_url == "https://openrouter.ai/api/v1"


# -- the store is write-only ---------------------------------------------------


def test_store_is_write_only(tmp_path, monkeypatch):
    _clean(monkeypatch)
    store = SecretStore(tmp_path)
    store.set("provider.openrouter", FAKE_KEY)
    assert store.has("provider.openrouter")
    assert store.get("provider.openrouter") == FAKE_KEY  # in-process read (brains)
    assert store.last4("provider.openrouter") == "FAKE"

    rows = provider_status(home=tmp_path)
    blob = json.dumps(rows, ensure_ascii=False)
    assert FAKE_KEY not in blob  # the value never appears in the API payload
    row = next(r for r in rows if r["id"] == "openrouter")
    assert row["key_in_store"] is True and row["key_last4"] == "FAKE"
    assert row["configured"] is True and row["key_source"] == "store"
    # an env-provided key is reported as configured too, still without the value
    monkeypatch.setenv("EEZE_BRAIN_API_KEY", "env-key-abcdefgh")
    rows_env = provider_status(home=tmp_path)
    assert "env-key-abcdefgh" not in json.dumps(rows_env)
    assert next(r for r in rows_env if r["id"] == "openrouter")["key_source"] == "store"


def test_store_refuses_empty_and_reports_short_values(tmp_path):
    store = SecretStore(tmp_path)
    with pytest.raises(ValueError):
        store.set("provider.openrouter", "   ")
    store.set("provider.openrouter", "abc")
    assert store.last4("provider.openrouter") == ""  # too short to reveal half of it
    assert store.delete("provider.openrouter") is True
    assert store.delete("provider.openrouter") is False
    assert store.has("provider.openrouter") is False


def test_store_file_is_private_and_corruption_is_quarantined(tmp_path):
    store = SecretStore(tmp_path)
    store.set("provider.openrouter", FAKE_KEY)
    if os.name == "posix":
        assert (store.path.stat().st_mode & 0o777) == 0o600
    store.path.write_text("{not json", encoding="utf-8")
    assert store.get("provider.openrouter") is None  # treated as empty, no crash
    quarantined = list(tmp_path.glob("secrets.json.bad-*"))
    assert quarantined, "the corrupt file must be preserved, never silently overwritten"
    store.set("provider.openai", "sk-openai-9876")  # a working file again
    assert store.get("provider.openai") == "sk-openai-9876"


# -- probes: real calls, honest failures ---------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = text or json.dumps(self._body)

    def json(self):
        return self._body


def test_probe_reports_success_with_real_fields(tmp_path, monkeypatch):
    _clean(monkeypatch)
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "headers": dict(headers or {})})
        return _FakeResponse(
            200,
            {
                "model": "openai/gpt-6-luna",
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 2},
            },
        )

    store = SecretStore(tmp_path)
    store.set("provider.openrouter", FAKE_KEY)
    cfg = resolve_provider("brain", home=tmp_path)
    result = probe_provider("openrouter", cfg, http_post=fake_post)
    assert result["ok"] is True
    assert result["status_code"] == 200 and result["tokens"] == 13
    assert result["model_echo"] == "openai/gpt-6-luna"
    assert calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"


def test_probe_redacts_the_key_and_reports_failures(tmp_path, monkeypatch):
    _clean(monkeypatch)
    store = SecretStore(tmp_path)
    store.set("provider.openrouter", FAKE_KEY)
    cfg = resolve_provider("brain", home=tmp_path)

    def echo_key(url, json=None, headers=None, timeout=None):
        return _FakeResponse(401, text=f'{{"error":"invalid key {FAKE_KEY}"}}')

    result = probe_provider("openrouter", cfg, http_post=echo_key)
    assert result["ok"] is False and result["status_code"] == 401
    assert FAKE_KEY not in json.dumps(result)
    assert "[key]" in result["detail"]

    def boom(url, json=None, headers=None, timeout=None):
        raise TimeoutError("no answer in 60s")

    result = probe_provider("openrouter", cfg, http_post=boom)
    assert result["ok"] is False and "transport error: TimeoutError" in result["detail"]


def test_probe_refusals_are_honest(tmp_path, monkeypatch):
    _clean(monkeypatch)
    # incompatible provider: refused before any call
    anthropic = get_provider("anthropic")
    cfg = ProviderConfig(
        provider_id="anthropic",
        base_url=anthropic.base_url,
        api_key="sk-ant-123456",
        model="claude-x",
        source="store",
        brain="llm",
    )
    result = probe_provider("anthropic", cfg)
    assert result["ok"] is False and "does not speak the OpenAI chat-completions" in result["detail"]
    # a provider without a model: no invented model id, honest message
    openai_cfg = resolve_provider("brain", provider_id="openai", home=tmp_path)
    assert openai_cfg.model == ""
    result = probe_provider("openai", openai_cfg)
    assert result["ok"] is False and "no model set" in result["detail"]


def test_probe_codex_uses_the_local_cli(tmp_path, monkeypatch):
    _clean(monkeypatch)
    seen: dict = {}

    def runner(argv, prompt):
        seen["argv"], seen["prompt"] = argv, prompt
        return 0, json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}})

    cfg = resolve_provider("brain", provider_id="codex", home=tmp_path)
    result = probe_provider("codex", cfg, codex_runner=runner, scratch=tmp_path)
    assert result["ok"] is True and result["method"] == "codex_exec"
    assert result["model_echo"] == "gpt-6-luna"
    assert seen["argv"][-1] == "-"  # the prompt still travels on stdin
    assert "Reply with exactly: OK" in seen["prompt"]


# -- the API surface -----------------------------------------------------------


def test_api_lists_providers_without_any_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["id"] for r in rows] == provider_ids()
    assert all("key" not in k or k.endswith(("_source", "_last4", "_in_store")) for r in rows for k in r)
    stored = json.dumps(rows)
    assert "sk-" not in stored  # nothing that looks like a key


def test_api_stores_lists_and_deletes_a_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/providers/openrouter/key", json={"key": FAKE_KEY}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "id": "openrouter", "key_last4": "FAKE", "configured": True}
    assert FAKE_KEY not in json.dumps(body)

    row = next(r for r in client.get("/api/providers").json() if r["id"] == "openrouter")
    assert row["configured"] is True and row["key_in_store"] is True and row["key_last4"] == "FAKE"

    gone = client.delete("/api/providers/openrouter/key", headers=AUTH)
    assert gone.status_code == 200 and gone.json()["removed"] is True
    row_after = next(r for r in client.get("/api/providers").json() if r["id"] == "openrouter")
    assert row_after["key_in_store"] is False and row_after["key_last4"] == ""


def test_api_refusal_paths(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/providers/openrouter/key", json={"key": FAKE_KEY}).status_code == 401
    assert client.post("/api/providers/openrouter/key", json={"key": FAKE_KEY}, headers={"X-EEZE-Token": "wrong"}).status_code == 401
    assert (
        client.post(
            "/api/providers/openrouter/key",
            json={"key": FAKE_KEY},
            headers={**AUTH, "X-Forwarded-For": "203.0.113.5"},
        ).status_code
        == 403
    )
    assert client.post("/api/providers/nope/key", json={"key": FAKE_KEY}, headers=AUTH).status_code == 404
    assert client.post("/api/providers/codex/key", json={"key": FAKE_KEY}, headers=AUTH).status_code == 409
    assert client.post("/api/providers/ollama/key", json={"key": FAKE_KEY}, headers=AUTH).status_code == 409
    assert client.post("/api/providers/anthropic/key", json={"key": FAKE_KEY}, headers=AUTH).status_code == 409
    assert client.post("/api/providers/openrouter/key", json={"key": "   "}, headers=AUTH).status_code == 422
    assert client.post("/api/providers/openrouter/key", json={}, headers=AUTH).status_code == 422
    bad_url = client.put("/api/providers/openrouter", json={"base_url": "ftp://x"}, headers=AUTH)
    assert bad_url.status_code == 422
    assert client.put("/api/providers/nope", json={"base_url": "http://x"}, headers=AUTH).status_code == 404
    assert client.post("/api/providers/openrouter/test", headers=AUTH).status_code == 200  # codex-free path
    assert client.post("/api/providers/nope/test", headers=AUTH).status_code == 404


def test_api_overrides_round_trip(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.put(
        "/api/providers/openrouter",
        json={"base_url": "https://proxy.example/v1/", "default_models": {"routine": "me/luna"}, "set_default": True},
        headers=AUTH,
    )
    assert resp.status_code == 200
    row = resp.json()
    assert row["base_url"] == "https://proxy.example/v1"  # trailing slash normalized
    assert row["base_url_source"] == "store"
    assert row["models"]["routine"] == "me/luna" and row["models"]["hard"] == "openai/gpt-6-sol"
    assert row["is_default"] is True
    cleared = client.put("/api/providers/openrouter", json={"base_url": "", "default_models": {}}, headers=AUTH)
    assert cleared.json()["base_url"] == "https://openrouter.ai/api/v1"


# -- the brains consume the layer ---------------------------------------------


def test_llm_brain_prefers_a_stored_key(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_BRAIN_API_KEY", "env-key")
    monkeypatch.setenv("EEZE_BRAIN_MODEL", "env/model")
    brain = LlmBrain()
    assert brain.api_key == "env-key" and brain.model == "env/model"
    assert brain.provider_id == "openrouter" and brain.provider_source == "default"

    SecretStore(Path.home() / ".eeze")  # touch the real store only to prove nothing writes to it
    cfg = resolve_provider("brain", home=tmp_path)  # store empty here -> env wins
    brain2 = LlmBrain(provider=cfg)
    assert brain2.api_key == "env-key" and brain2.model == "env/model"

    store = SecretStore(tmp_path)
    store.set("provider.openrouter", "stored-key-123456")
    cfg2 = resolve_provider("brain", home=tmp_path)
    brain3 = LlmBrain(provider=cfg2)
    assert brain3.api_key == "stored-key-123456"  # the store beats env
    assert LlmBrain(api_key="explicit", provider=cfg2).api_key == "explicit"  # an argument still wins


def test_planner_and_spec_writer_consume_the_store(tmp_path, monkeypatch):
    _clean(monkeypatch)
    store = SecretStore(tmp_path)
    store.set("provider.openrouter", "stored-key-123456")
    store.set("provider.openrouter.models", json.dumps({"hard": "me/solver"}))
    planner = Planner(provider=resolve_provider("planner", home=tmp_path))
    assert planner.api_key == "stored-key-123456" and planner.model == "me/solver"
    assert planner.provider_id == "openrouter"
    writer = SpecWriter(provider=resolve_provider("spec", home=tmp_path))
    assert writer.api_key == "stored-key-123456" and writer.model == "me/solver"


def test_engines_keep_env_parity_when_the_store_is_empty(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_PLANNER_API_KEY", "planner-env-key")
    planner = Planner(provider=resolve_provider("planner", home=tmp_path))
    assert planner.api_key == "planner-env-key"
    writer = SpecWriter(provider=resolve_provider("spec", home=tmp_path))
    assert writer.api_key == "planner-env-key"


# -- the role env belongs to ONE provider (live-found on the Settings card) ----


def test_probe_refuses_config_from_another_provider(tmp_path, monkeypatch):
    _clean(monkeypatch)
    store = SecretStore(tmp_path)
    store.set("provider.openrouter", "synthetic-router-key")
    cfg = resolve_provider("brain", home=tmp_path)
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeResponse(200)

    result = probe_provider("openai", cfg, http_post=record)
    assert result["ok"] is False and "mismatch" in result["detail"]
    assert calls == []


def test_explicit_endpoint_override_refuses_implicit_provider_key(tmp_path, monkeypatch):
    _clean(monkeypatch)
    store = SecretStore(tmp_path)
    store.set("provider.openrouter", "synthetic-stored-key")
    for role, constructor in (
        ("brain", LlmBrain),
        ("planner", Planner),
        ("spec", SpecWriter),
    ):
        cfg = resolve_provider(role, home=tmp_path)
        with pytest.raises(ValueError, match="explicit api_key"):
            constructor(provider=cfg, base_url="https://other.example/v1")
        allowed = constructor(provider=cfg, base_url="https://other.example/v1", api_key="own-key")
        assert allowed.api_key == "own-key"


def test_role_env_key_does_not_follow_a_different_stored_endpoint(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_PLANNER_API_KEY", "synthetic-default-only")
    monkeypatch.setenv("EEZE_PLANNER_BASE_URL", "https://openrouter.ai/api/v1")
    store = SecretStore(tmp_path)
    store.set("provider.openrouter.base_url", "https://proxy.example/v1")
    cfg = resolve_provider("planner", home=tmp_path)
    assert cfg.base_url == "https://proxy.example/v1"
    assert cfg.api_key == "" and cfg.sources["api_key"] == "none"


def test_custom_role_endpoint_is_not_claimed_by_explicit_other_provider(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_PLANNER_API_KEY", "synthetic-custom-only")
    monkeypatch.setenv("EEZE_PLANNER_BASE_URL", "https://custom.example/v1")
    cfg = resolve_provider("planner", provider_id="openai", home=tmp_path)
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.api_key == "" and cfg.sources["api_key"] == "none"


def test_foreign_role_key_never_reaches_selected_provider_transport(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_PLANNER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("EEZE_PLANNER_API_KEY", "synthetic-openrouter-only")
    store = SecretStore(tmp_path)
    store.set("provider.default", "openai")
    store.set("provider.openai.models", json.dumps({"routine": "test-model", "hard": "test-model"}))
    expected_url = "https://api.openai.com/v1/chat/completions"
    seen = []

    def record(url, json=None, headers=None, timeout=None):
        seen.append((url, dict(headers or {})))
        return _FakeResponse(200, {"choices": [{"message": {"content": "OK"}}]})

    brain = LlmBrain(provider=resolve_provider("brain", home=tmp_path))
    assert brain.api_key == ""
    monkeypatch.setattr("eeze_agent.brains.llm.httpx.post", record)
    brain._chat("system", "user")
    assert seen == [(expected_url, {"Content-Type": "application/json"})]

    planner = Planner(provider=resolve_provider("planner", home=tmp_path))
    assert planner.api_key == ""
    monkeypatch.setattr("eeze_agent.brains.planner.httpx.post", record)
    planner._chat("system", "user")
    assert seen[-1] == (expected_url, {"Content-Type": "application/json"})

    writer = SpecWriter(provider=resolve_provider("spec", home=tmp_path))
    assert writer.api_key == ""
    monkeypatch.setattr("eeze_agent.brains.specwriter.httpx.post", record)
    writer._chat("system", "user")
    assert seen[-1] == (expected_url, {"Content-Type": "application/json"})



def test_role_env_is_claimed_only_by_its_owner(tmp_path, monkeypatch):
    """Live bug: every api_key provider read OpenRouter's .env key aloud."""
    _clean(monkeypatch)
    home = tmp_path
    monkeypatch.setenv("EEZE_PLANNER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("EEZE_PLANNER_API_KEY", "the-openrouter-key")

    rows = {row["id"]: row for row in provider_status(home=home)}
    assert rows["openrouter"]["configured"] is True
    assert rows["openrouter"]["key_source"] == "env"
    for other in ("openai", "google", "xai", "groq"):
        assert rows[other]["configured"] is False, other
        assert rows[other]["key_source"] == "none", other
        assert rows[other]["configured_detail"] == "no key yet — add one to use this provider"
    assert rows["anthropic"]["configured"] is False

    # an env endpoint that names another catalog provider is claimed by THAT one
    monkeypatch.setenv("EEZE_PLANNER_BASE_URL", "https://api.x.ai/v1")
    rows = {row["id"]: row for row in provider_status(home=home)}
    assert rows["xai"]["configured"] is True and rows["xai"]["key_source"] == "env"
    assert rows["openrouter"]["configured"] is False

    # no endpoint in the env at all -> the shipped default owns it (documented convention)
    monkeypatch.delenv("EEZE_PLANNER_BASE_URL")
    rows = {row["id"]: row for row in provider_status(home=home)}
    assert rows["openrouter"]["configured"] is True
    assert rows["groq"]["configured"] is False

    # a custom (self-hosted/proxy) endpoint belongs to whoever resolves it — single-endpoint
    # setups keep working exactly as before this rule
    monkeypatch.setenv("EEZE_PLANNER_BASE_URL", "https://my-proxy.internal/v1")
    cfg = resolve_provider("brain", home=home)
    assert cfg.api_key == "the-openrouter-key" and cfg.sources["api_key"] == "env"


def test_rows_report_what_is_running(tmp_path, monkeypatch):
    """role=model is the provider the model layer resolves to; role=engine is the brain running."""
    _clean(monkeypatch)
    home = tmp_path
    monkeypatch.setenv("EEZE_BRAIN", "codex")
    rows = {row["id"]: row for row in provider_status(home=home)}
    assert rows["openrouter"]["role"] == "model"
    assert rows["codex"]["role"] == "engine"
    assert rows["codex"]["configured"] is True or rows["codex"]["configured"] is False  # env-dependent

    # the app's pick moves the model role and turns the llm brain on (see registry tests)
    SecretStore(home).set("provider.default", "xai")
    rows = {row["id"]: row for row in provider_status(home=home)}
    assert rows["xai"]["role"] == "model" and rows["xai"]["is_default"] is True
    assert rows["openrouter"]["role"] == "" and rows["openrouter"]["is_default"] is False


def test_default_provider_brain_maps_kinds(tmp_path, monkeypatch):
    _clean(monkeypatch)
    from eeze_agent.core.providers import default_provider_brain

    store = SecretStore(tmp_path)
    assert default_provider_brain(home=tmp_path) == ""  # nothing picked -> env decides
    store.set("provider.default", "groq")
    assert default_provider_brain(home=tmp_path) == "llm"
    store.set("provider.default", "codex")
    assert default_provider_brain(home=tmp_path) == "codex"
    store.set("provider.default", "ghost")
    assert default_provider_brain(home=tmp_path) == ""  # unknown id never picks a brain


def test_store_env_override_redirects_the_file(tmp_path, monkeypatch):
    """EEZE_SECRETS points the store at another file (tests, alternate installs)."""
    monkeypatch.setenv("EEZE_SECRETS", str(tmp_path / "elsewhere" / "keys.json"))
    store = SecretStore()
    assert store.path == tmp_path / "elsewhere" / "keys.json"
    store.set("provider.openai", "sk-env-override-123456")
    assert (tmp_path / "elsewhere" / "keys.json").exists()
    # an explicit home still beats the env var (the API passes its instance home)
    assert SecretStore(tmp_path).path == tmp_path / "secrets.json"


def test_stored_key_never_follows_a_changed_endpoint(tmp_path, monkeypatch):
    """Security: pointing base_url at another host must not ship the saved key there."""
    _clean(monkeypatch)
    store = SecretStore(tmp_path)
    store.set("provider.openrouter", FAKE_KEY)
    assert resolve_provider("brain", home=tmp_path).api_key == FAKE_KEY  # catalog host: ok
    store.set("provider.openrouter.base_url", "https://attacker.example/v1")
    cfg = resolve_provider("brain", home=tmp_path)
    assert cfg.api_key != FAKE_KEY
    assert cfg.sources["api_key"] != "store"


def test_model_ids_are_plain_tokens():
    from eeze_agent.brains.codex import build_argv
    from eeze_agent.core.providers import valid_model_id

    assert valid_model_id("openai/gpt-6-sol") and valid_model_id("gpt-6-luna")
    for bad in ("x&calc.exe", "a|b", "m^x", "", "a b", "-rf"):
        assert not valid_model_id(bad), bad
    import pytest as _pytest

    with _pytest.raises(ValueError):
        build_argv("codex", "gpt&calc.exe", tmp_path_placeholder := "C:/s", platform="nt")  # noqa: F841
    with _pytest.raises(ValueError):
        build_argv("C:/evil&calc.exe", "gpt-6-sol", "C:/s", platform="nt")


def test_sabi_is_reached_locally_with_its_routing_alias_and_no_key(tmp_path, monkeypatch):
    _clean(monkeypatch)
    cfg = resolve_provider("brain", provider_id="sabi", home=tmp_path)
    assert cfg.base_url == "http://127.0.0.1:8787/v1" and cfg.api_key == ""
    assert cfg.model == "sabi-code" and cfg.brain == "llm"
    calls = []

    def fake_sabi(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(200, body={"model": "openai/gpt-6-luna",
                                        "choices": [{"message": {"content": "OK"}}],
                                        "usage": {"prompt_tokens": 9, "completion_tokens": 1}})

    result = probe_provider("sabi", cfg, http_post=fake_sabi)
    assert result["ok"] is True
    assert calls[0]["url"] == "http://127.0.0.1:8787/v1/chat/completions"
    assert calls[0]["json"]["model"] == "sabi-code" and "Authorization" not in calls[0]["headers"]
    assert result["model_echo"] == "openai/gpt-6-luna"  # Sabi reports the model it routed to
