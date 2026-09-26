"""v2 — model router: rules floor, Jev decision, escalation, registry wiring, costs."""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from eeze_agent.brains.router import (
    DEFAULT_TIERS,
    escalated_tier,
    route_task,
    signals_for,
    tier_of,
    tiers_for,
)
from eeze_agent.core.models import StepSpec, TaskSpec


def _task(name: str = "t", app: str = "notepad", steps: list[StepSpec] | None = None) -> TaskSpec:
    return TaskSpec(
        name=name,
        app=app,
        steps=steps
        or [
            StepSpec(id="s1", action="set_text", intent="set the document text to {token}", text="{token}")
        ],
    )


def _click_steps(n: int) -> list[StepSpec]:
    return [
        StepSpec(id=f"c{i}", action="click", intent=f"press the button number {i}")
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _rules_mode(monkeypatch):
    """Never call Jev from tests unless the test itself asks for it."""
    monkeypatch.setenv("EEZE_ROUTER", "rules")
    monkeypatch.delenv("EEZE_BRAIN_MODEL", raising=False)


# ---------------- rules floor ----------------

def test_script_only_task_is_routine():
    task = _task(
        name="video-edit-agent",
        app="",
        steps=[StepSpec(id="edit", action="run_script", intent="run the edit", command="eeze video x.yaml")],
    )
    decision = route_task(task)
    assert decision.tier == "routine" and decision.source == "rules"
    assert decision.model == DEFAULT_TIERS["routine"]
    assert "script-only" in decision.reason


def test_hard_markers_win():
    task = _task(
        name="brand-3d",
        app="blender",
        steps=[StepSpec(id="r", action="click", intent="open the 3D render settings panel")],
    )
    decision = route_task(task)
    assert decision.tier == "hard" and decision.model == DEFAULT_TIERS["hard"]
    assert "hard markers" in decision.reason


def test_routine_markers_win_over_small_gui():
    task = _task(name="invoices-daily", steps=[StepSpec(id="s", action="click", intent="open the inbox mailbox")])
    assert route_task(task).tier == "routine"


def test_small_gui_defaults_routine_large_is_hard():
    small = route_task(_task(steps=_click_steps(4)))
    large = route_task(_task(steps=_click_steps(7)))
    assert small.tier == "routine" and "small GUI" in small.reason
    assert large.tier == "hard" and "large GUI" in large.reason


def test_signals_for_goal_string():
    signals = signals_for("make a 10s turntable of the logo in Blender and export MP4")
    assert signals.name == "<goal>"
    assert route_task("make a 10s turntable of the logo in Blender and export MP4").tier == "hard"


def test_escalation_moves_up_the_ladder_and_caps():
    assert escalated_tier("routine", DEFAULT_TIERS) == "hard"
    assert escalated_tier("hard", DEFAULT_TIERS) == "hard"
    decision = route_task(_task(), escalate_from="routine")
    assert decision.source == "escalated" and decision.tier == "hard"


# ---------------- Jev decides ----------------

class _FakeChoice:
    def __init__(self, choice, confidence, probabilities=None):
        self.choice = choice
        self.confidence = confidence
        self.probabilities = probabilities or {}


class _FakeResponse:
    def __init__(self, answer, tokens=550):
        self.answers = {"route": answer}
        self.usage = types.SimpleNamespace(input_tokens=tokens, output_tokens=8)
        self.model = "jev-1.13.0"
        self.request_id = "req_test"


class _FakeClient:
    def __init__(self, answer=None, error: Exception | None = None):
        self.answer = answer
        self.error = error
        self.calls = 0

    def system_one(self, *, state, questions):
        self.calls += 1
        if self.error:
            raise self.error
        return _FakeResponse(self.answer)


def _jev_env(monkeypatch):
    monkeypatch.setenv("EEZE_ROUTER", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-used")


def test_jev_decides_route(monkeypatch):
    _jev_env(monkeypatch)
    client = _FakeClient(_FakeChoice("hard", 0.99, {"hard": 0.99, "routine": 0.01}))
    decision = route_task(_task(), jev_client=client)
    assert client.calls == 1
    assert decision.source == "jev" and decision.tier == "hard"
    assert decision.model == DEFAULT_TIERS["hard"]
    assert decision.confidence == 0.99 and decision.tokens == 550
    assert "jev chose" in decision.reason


def test_jev_routine_choice(monkeypatch):
    _jev_env(monkeypatch)
    decision = route_task(_task(), jev_client=_FakeClient(_FakeChoice("routine", 0.95)))
    assert decision.source == "jev" and decision.tier == "routine"


def test_jev_uncertain_or_broken_falls_back_to_rules(monkeypatch):
    _jev_env(monkeypatch)
    low = route_task(_task(), jev_client=_FakeClient(_FakeChoice("hard", 0.2)))
    assert low.source == "rules-fallback" and "below floor" in low.reason
    off_menu = route_task(_task(), jev_client=_FakeClient(_FakeChoice("gemini", 0.9)))
    assert off_menu.source == "rules-fallback" and "not one of" in off_menu.reason
    boom = route_task(_task(), jev_client=_FakeClient(error=RuntimeError("network down")))
    assert boom.source == "rules-fallback" and "jev unavailable" in boom.reason


# ---------------- precedence ----------------

def _repo(tmp_path: Path, body: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "agents.yaml").write_text(body, encoding="utf-8")
    return repo


def test_pin_beats_everything(tmp_path):
    decision = route_task(_task(), pin="openai/gpt-6-sol", agent_id="ops", repo_root=tmp_path)
    assert decision.source == "pin" and decision.model == "openai/gpt-6-sol"
    assert decision.tier == tier_of("openai/gpt-6-sol", DEFAULT_TIERS)


def test_agents_yaml_can_force_a_tier(tmp_path):
    repo = _repo(
        tmp_path,
        "agents:\n  - id: ops\n    name: Ops\n    model:\n      brain: llm\n      tier: hard\n",
    )
    decision = route_task(_task(), agent_id="ops", repo_root=repo)
    assert decision.source == "config" and decision.tier == "hard"


def test_agents_yaml_tiers_override_models(tmp_path):
    repo = _repo(
        tmp_path,
        "agents:\n  - id: ops\n    name: Ops\n    model:\n      brain: llm\n"
        "      tiers:\n        routine: some/cheap\n        hard: some/strong\n",
    )
    tiers = tiers_for("ops", repo)
    assert tiers == {"routine": "some/cheap", "hard": "some/strong"}
    assert route_task(_task(), agent_id="ops", repo_root=repo).model == "some/cheap"


# ---------------- registry wiring ----------------

def test_make_brain_routes_only_llm_with_a_task(tmp_path, monkeypatch):
    from eeze_agent.brains.llm import LlmBrain
    from eeze_agent.brains.registry import make_brain

    monkeypatch.setenv("EEZE_ROUTER", "rules")
    repo = _repo(
        tmp_path,
        "agents:\n  - id: ops\n    name: Ops\n    model:\n      brain: llm\n",
    )
    hard_task = _task(
        name="scene-render",
        app="blender",
        steps=[StepSpec(id="r", action="click", intent="open the 3D render settings panel")],
    )
    brain = make_brain(agent_id="ops", repo_root=repo, task=hard_task)
    assert isinstance(brain, LlmBrain)
    assert brain.model == DEFAULT_TIERS["hard"]
    assert brain.route.source == "rules" and brain.route.tier == "hard"

    pinned = make_brain(agent_id="ops", repo_root=repo, task=hard_task, model="pinned/model")
    assert pinned.model == "pinned/model" and not hasattr(pinned, "route")

    unpinned = make_brain(agent_id="ops", repo_root=repo)
    assert not hasattr(unpinned, "route")

    monkeypatch.setenv("EEZE_ROUTER", "off")
    off = make_brain(agent_id="ops", repo_root=repo, task=hard_task)
    assert not hasattr(off, "route")

    jev_repo = _repo(tmp_path / "x", "agents:\n  - id: default\n    name: D\n    model:\n      brain: jev\n")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-used")
    from eeze_agent.brains.jev import JevBrain

    assert isinstance(make_brain(agent_id="default", repo_root=jev_repo, task=hard_task), JevBrain)


# ---------------- per-model cost rollup ----------------

def test_summarize_prices_each_model(tmp_path):
    from eeze_agent.core.journal import RunJournal
    from eeze_agent.core.loop import summarize

    journal = RunJournal(tmp_path, "rs-router", agent_id="default")
    journal.event(
        "judgment", run_index=1, judgment_kind="select_element", model="openai/gpt-6-luna",
        tokens=1094, ms=1900.0, confidence=1.0,
    )
    journal.event(
        "judgment", run_index=1, judgment_kind="verify", model="jev-1.13.0",
        tokens=1520, ms=330.0, noul=0.9,
    )
    journal.close()
    summary = summarize(journal, [], 1)
    assert summary["models"]["openai/gpt-6-luna"]["calls"] == 1
    assert summary["models"]["openai/gpt-6-luna"]["cost_estimate_usd"] == pytest.approx(0.0001203, abs=1e-7)
    assert summary["models"]["jev-1.13.0"]["cost_estimate_usd"] == pytest.approx(0.0000638, abs=1e-7)
    assert summary["cost_estimate_usd"] == pytest.approx(0.0001841, abs=1e-7)


def test_model_route_event_is_json_safe():
    decision = route_task(_task(), pin="openai/gpt-6-sol")
    assert json_safe(decision.as_event())


def json_safe(value) -> bool:
    import json

    json.dumps(value)
    return True


# ---------------- provider tier mapping (P3) ----------------

def test_provider_tier_models_feed_the_router(tmp_path, monkeypatch):
    """P3: the ACTIVE provider's models decide the tiers; an empty catalog must never win."""
    import json as _json

    from eeze_agent.core.providers import tier_models
    from eeze_agent.core.secrets_local import SecretStore

    monkeypatch.setenv("EEZE_ROUTER", "rules")
    monkeypatch.setenv("EEZE_SECRETS", str(tmp_path / "secrets.json"))
    for var in ("EEZE_PLANNER_MODEL", "EEZE_BRAIN_MODEL", "EEZE_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    store = SecretStore()

    # nobody named a provider -> exactly today's behaviour
    assert tiers_for("default", None) == DEFAULT_TIERS
    # a measured provider keeps its own names; a never-measured one keeps the built-ins
    # instead of routing to a blank or invented id
    assert tiers_for("default", None, "openrouter")["routine"] == "openai/gpt-6-luna"
    assert tier_models("xai") == {"routine": "", "hard": ""}
    assert tiers_for("default", None, "xai") == DEFAULT_TIERS

    # the user's own mapping (store override for the ACTIVE provider) feeds both tiers,
    # and the decision a run journals carries THAT model
    store.set("provider.xai.models", _json.dumps({"routine": "grok-4-fast", "hard": "grok-4"}))
    assert tiers_for("default", None, "xai") == {"routine": "grok-4-fast", "hard": "grok-4"}
    routine = route_task(_task("invoice extraction"), provider_id="xai")
    assert routine.tier == "routine" and routine.model == "grok-4-fast"
    hard = route_task(_task(name="scene", app="blender"), provider_id="xai")
    assert hard.tier == "hard" and hard.model == "grok-4"

    # agents.yaml stays the most specific layer (per tier)
    repo = _repo(
        tmp_path,
        "agents:\n  - id: ops\n    name: Ops\n    model:\n      brain: llm\n"
        "      tiers:\n        routine: me/pinned\n",
    )
    assert tiers_for("ops", repo, "xai")["routine"] == "me/pinned"
    assert tiers_for("ops", repo, "xai")["hard"] == "grok-4"

    # an unknown provider id keeps the defaults — never a guess
    assert tiers_for("default", None, "nope") == DEFAULT_TIERS


def test_make_brain_carries_the_active_provider(tmp_path, monkeypatch):
    """The provider chosen on the Settings screen is what an llm run uses (key, endpoint, tiers)."""
    import json as _json

    from eeze_agent.brains.registry import make_brain
    from eeze_agent.core.secrets_local import SecretStore

    monkeypatch.setenv("EEZE_ROUTER", "rules")
    monkeypatch.setenv("EEZE_SECRETS", str(tmp_path / "secrets.json"))
    for var in (
        "EEZE_BRAIN_API_KEY",
        "EEZE_PLANNER_API_KEY",
        "EEZE_PLANNER_MODEL",
        "EEZE_BRAIN_MODEL",
        "EEZE_BRAIN_BASE_URL",
        "EEZE_PLANNER_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    store = SecretStore()
    store.set("provider.default", "xai")
    store.set("provider.xai", "xai-key-123456")
    store.set("provider.xai.models", _json.dumps({"routine": "grok-4-fast"}))
    repo = _repo(tmp_path, "agents:\n  - id: ops\n    name: Ops\n    model:\n      brain: llm\n")

    brain = make_brain(agent_id="ops", repo_root=repo, task=_task("invoice extraction"))
    assert brain.provider_id == "xai"
    assert brain.api_key == "xai-key-123456"
    assert brain.base_url == "https://api.x.ai/v1"
    assert brain.model == "grok-4-fast" and brain.route.model == "grok-4-fast"
    assert brain.provider_source == "store"


def test_the_app_provider_pick_decides_the_brain(tmp_path, monkeypatch):
    """P3: "Use this one" on the Settings screen is real — the pick beats EEZE_BRAIN, never an arg."""
    from eeze_agent.brains.registry import resolve_brain_name
    from eeze_agent.core.secrets_local import SecretStore

    monkeypatch.setenv("EEZE_SECRETS", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("EEZE_BRAIN", "codex")
    repo = _repo(tmp_path, "agents:\n  - id: ops\n    name: Ops\n    model:\n      brain: llm\n")

    # nothing picked yet -> the env decides (exactly today's behaviour)
    assert resolve_brain_name(repo_root=repo) == "codex"
    # the app's pick wins over the env; an explicit argument still wins over everything
    SecretStore().set("provider.default", "groq")
    assert resolve_brain_name(repo_root=repo) == "llm"
    assert resolve_brain_name(name="jev", repo_root=repo) == "jev"
    # the local subscription is selectable through the same key
    SecretStore().set("provider.default", "codex")
    assert resolve_brain_name(repo_root=repo) == "codex"
