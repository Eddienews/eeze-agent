"""Jev (TypeSafe) is optional: without its key the loop uses the provider chosen in the app."""

from __future__ import annotations

from eeze_agent.brains import registry


def test_no_typesafe_key_falls_back_to_llm(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("eeze_agent.brains.jev._ensure_env", lambda: None)
    monkeypatch.setattr(registry, "resolve_brain_name", lambda **_: "jev")
    calls = []
    monkeypatch.setattr(registry, "_routed_llm", lambda **kw: calls.append(kw) or "llm-brain")
    assert registry.make_brain(agent_id="default") == "llm-brain"
    assert calls


def test_explicit_jev_is_respected(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    made = []

    class FakeJev:
        def __init__(self, **kw):
            made.append(kw)

    monkeypatch.setattr("eeze_agent.brains.jev.JevBrain", FakeJev)
    monkeypatch.setattr(registry, "resolve_brain_name", lambda **_: "jev")
    assert isinstance(registry.make_brain(agent_id="default"), FakeJev)
