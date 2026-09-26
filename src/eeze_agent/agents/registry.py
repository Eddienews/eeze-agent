"""Agent registry — resolves agent ids to Agent definitions.

F1 seeds a single built-in ``default`` agent; an ``agents.yaml`` at the repo root
can override or extend it. Persistence (SQLite) arrives in F3; the model and the
``agent_id`` threading land now so nothing needs refactoring later (ADR-0002).
"""

from __future__ import annotations

from pathlib import Path

from eeze_agent.agents.models import Agent

DEFAULT_AGENT = Agent(
    id="default",
    name="Default",
    role="generalist",
    permissions={
        "risk_classes": ["read", "write_local"],
        "apps": ["*"],
        "allow_foreground": False,
    },
    tools=["*"],
)


class AgentRegistry:
    def __init__(self, agents: list[Agent] | None = None) -> None:
        if agents is None:
            agents = [DEFAULT_AGENT]
        self._agents = {a.id: a for a in agents}

    @classmethod
    def _load_agents(cls, path: Path) -> list[Agent]:
        """Parse the yaml; empty/missing → [] (no fallback — callers decide)."""
        if not path.exists():
            return []
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [Agent(**a) for a in data.get("agents", [])]

    @classmethod
    def from_yaml(cls, path: Path) -> AgentRegistry:
        agents = cls._load_agents(path)
        return cls(agents) if agents else cls()

    @classmethod
    def from_sources(cls, repo_path: Path, user_path: Path | None = None) -> AgentRegistry:
        """Repo agents + user overrides (~/.eeze/agents.yaml wins per id; may add new)."""
        agents = cls._load_agents(repo_path)
        if user_path is not None and user_path.exists():
            by_id = {a.id: a for a in agents}
            for agent in cls._load_agents(user_path):
                by_id[agent.id] = agent  # user wins per id; an empty user file changes nothing
            agents = list(by_id.values())
        return cls(agents) if agents else cls()

    def get(self, agent_id: str) -> Agent:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {agent_id!r} (known: {self.ids()})") from exc

    def default(self) -> Agent:
        return self._agents.get("default") or next(iter(self._agents.values()))

    def ids(self) -> list[str]:
        return sorted(self._agents)


def load_registry(repo_root: Path, home: Path | None = None) -> AgentRegistry:
    """The runtime registry: ``agents.yaml`` at the repo + ``~/.eeze/agents.yaml`` overrides."""
    home = home or Path.home() / ".eeze"
    return AgentRegistry.from_sources(repo_root / "agents.yaml", home / "agents.yaml")
