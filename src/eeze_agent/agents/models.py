"""Agent model — multi-agent support from day one (F1: a single `default` agent).

Product vision: the user can create multiple named agents (e.g. 'Fin' for finance,
'Inbox' for email, 'Scout' for research). Each agent has isolated memory, its own
routines, its own permissions/tools, and appears separately in the approvals inbox.

Design consequence (ADR-0002): every run/step/judgment/action record carries
``agent_id``, and the Brain / Driver / Planner ports receive an ``AgentContext``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Agent(BaseModel):
    id: str
    name: str
    role: str = "generalist"
    description: str | None = None
    permissions: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=lambda: ["*"])
    # Brain selection per agent (v2): {"brain": "jev" | "llm", "planner": "<model id>"}
    model: dict[str, Any] = Field(default_factory=dict)
    # Daily spend cap in USD for paid model calls (None = EEZE_BUDGET_USD_DAILY / default;
    # 0 = no cap). Enforced by core.spend before every paid judgment.
    budget_usd_daily: float | None = Field(default=None, ge=0)


class AgentContext(BaseModel):
    """The agent scope threaded through ports and the loop for one run-set."""

    agent: Agent
    runset_id: str | None = None

    @property
    def agent_id(self) -> str:
        return self.agent.id
