"""v2 — LlmBrain judgments (fake client) + brain resolution (env / agents.yaml)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eeze_agent.agents.models import Agent, AgentContext
from eeze_agent.brains.llm import LlmBrain, clamp01
from eeze_agent.brains.registry import make_brain, resolve_brain_name
from eeze_agent.core.models import Candidate

CTX = AgentContext(agent=Agent(id="default", name="Default"))


def _cands() -> list[Candidate]:
    return [
        Candidate(id="c0", role="Document", label="Text editor", element_index=0, token="t0"),
        Candidate(id="c1", role="MenuItem", label="File", element_index=1, token="t1"),
    ]


def test_select_element_parses_json_and_prompt():
    seen: dict = {}

    def fake(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = json.loads(user)
        return '{"answer": "c1", "confidence": 0.82}'

    brain = LlmBrain(client=fake, model="fake/model")
    judgment = brain.select_element(CTX, intent="open the File menu", state={"elements": 3}, candidates=_cands())
    assert judgment.kind == "select_element"
    assert judgment.answer == "c1" and judgment.confidence == 0.82
    assert judgment.model == "fake/model" and judgment.ms >= 0
    assert seen["user"]["instruction"] == "open the File menu"
    assert [c["id"] for c in seen["user"]["candidates"]] == ["c0", "c1"]
    assert "none_match" in seen["user"]


def test_select_element_tolerates_fenced_json_and_none_match():
    brain = LlmBrain(client=lambda s, u: "```json\n{\"answer\": \"none_match\", \"confidence\": 0.4}\n```")
    judgment = brain.select_element(CTX, intent="x", state={}, candidates=_cands())
    assert judgment.answer == "none_match" and judgment.confidence == 0.4


def test_select_element_garbage_is_a_retry_not_a_crash():
    brain = LlmBrain(client=lambda s, u: "I think maybe the second one?")
    judgment = brain.select_element(CTX, intent="x", state={}, candidates=_cands())
    assert judgment.answer is None and judgment.confidence is None


def test_select_element_transport_error_degrades():
    def boom(system: str, user: str) -> str:
        raise RuntimeError("network down")

    brain = LlmBrain(client=boom)
    judgment = brain.select_element(CTX, intent="x", state={}, candidates=_cands())
    assert judgment.answer is None


def test_verify_probability_and_clamping():
    brain = LlmBrain(client=lambda s, u: '{"probability": 0.95, "reason": "text matches"}')
    judgment = brain.verify(CTX, statement="the document equals 'x'", state={})
    assert judgment.kind == "verify" and judgment.noul == 0.95

    high = LlmBrain(client=lambda s, u: '{"probability": 4}')
    assert high.verify(CTX, statement="x", state={}).noul == 1.0
    low = LlmBrain(client=lambda s, u: '{"probability": -1}')
    assert low.verify(CTX, statement="x", state={}).noul == 0.0

    broken = LlmBrain(client=lambda s, u: "not json")
    assert broken.verify(CTX, statement="x", state={}).noul is None


def test_clamp01():
    assert clamp01("0.5") == 0.5 and clamp01(None) is None and clamp01("abc") is None


# ---------------- resolution ----------------

def _repo_with_brain(tmp_path: Path, brain: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "agents.yaml").write_text(
        f"agents:\n  - id: default\n    name: Default\n    model:\n      brain: {brain}\n",
        encoding="utf-8",
    )
    return repo


def test_resolve_precedence(tmp_path: Path, monkeypatch):
    repo = _repo_with_brain(tmp_path, "llm")
    monkeypatch.delenv("EEZE_BRAIN", raising=False)
    assert resolve_brain_name(agent_id="default", repo_root=repo) == "llm"  # yaml
    monkeypatch.setenv("EEZE_BRAIN", "jev")
    assert resolve_brain_name(agent_id="default", repo_root=repo) == "jev"  # env beats yaml
    assert resolve_brain_name(name="llm", agent_id="default", repo_root=repo) == "llm"  # explicit beats all
    with pytest.raises(ValueError):
        resolve_brain_name(name="gpt5", agent_id="default", repo_root=None)


def test_make_brain_builds_llm_and_defaults_to_jev(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-used")
    monkeypatch.delenv("EEZE_BRAIN", raising=False)
    repo = _repo_with_brain(tmp_path, "llm")
    assert isinstance(make_brain(agent_id="default", repo_root=repo), LlmBrain)
    monkeypatch.setenv("EEZE_BRAIN", "llm")
    assert isinstance(make_brain(agent_id="default", repo_root=None), LlmBrain)

    monkeypatch.delenv("EEZE_BRAIN", raising=False)
    repo_jev = _repo_with_brain(tmp_path / "x", "jev")
    from eeze_agent.brains.jev import JevBrain

    brain = make_brain(agent_id="default", repo_root=repo_jev)
    assert isinstance(brain, JevBrain) and not isinstance(brain, LlmBrain)
