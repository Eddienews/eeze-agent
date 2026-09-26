"""v2 — named agents: registry, per-agent brain + policy, routine agent wiring."""

from __future__ import annotations

from pathlib import Path

from eeze_agent.agents.registry import AgentRegistry
from eeze_agent.brains.llm import LlmBrain
from eeze_agent.brains.registry import make_brain
from eeze_agent.core.risk import policy_for_agent
from eeze_agent.core.routines import RoutineStore

REPO = Path(__file__).resolve().parents[1]


def test_repo_agents_yaml_has_named_agents():
    registry = AgentRegistry.from_yaml(REPO / "agents.yaml")
    ids = set(registry.ids())
    assert {"default", "finance", "ops"} <= ids
    assert registry.get("ops").model.get("brain") == "llm"
    assert registry.get("finance").model.get("brain") == "jev"


def test_per_agent_policy_lanes(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-used")
    monkeypatch.delenv("EEZE_BRAIN", raising=False)
    registry = AgentRegistry.from_yaml(REPO / "agents.yaml")

    default_policy = policy_for_agent(registry.get("default").permissions)
    ops_policy = policy_for_agent(registry.get("ops").permissions)
    assert default_policy.allows("write_local") and not default_policy.allows("external_send")
    assert ops_policy.allows("read") and not ops_policy.allows("write_local")


def test_make_brain_per_agent_from_repo_yaml(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-used")
    monkeypatch.delenv("EEZE_BRAIN", raising=False)
    assert isinstance(make_brain(agent_id="ops", repo_root=REPO), LlmBrain)
    from eeze_agent.brains.jev import JevBrain

    finance = make_brain(agent_id="finance", repo_root=REPO)
    assert isinstance(finance, JevBrain)


def test_routine_can_belong_to_an_agent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EEZE_DB", str(tmp_path / "eeze.db"))
    store = RoutineStore()
    row = store.add(
        "nightly", name="Nightly", kind="task", schedule={"type": "every", "minutes": 120},
        params={"task_path": "tasks/x.yaml"}, agent_id="finance",
    )
    assert row["agent_id"] == "finance"
    assert store.get("nightly")["agent_id"] == "finance"
