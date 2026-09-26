"""Daily spend cap per agent: ledger, precedence, and the loop stopping before overspending."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_approvals import FakeDriver

from eeze_agent.agents.models import Agent, AgentContext
from eeze_agent.core import spend
from eeze_agent.core.journal import RunJournal
from eeze_agent.core.loop import run_set
from eeze_agent.core.models import Judgment, StepSpec, TaskSpec
from eeze_agent.core.risk import Policy


def test_ledger_records_and_sums_per_agent():
    assert spend.record("a", "openai/gpt-6-sol", 1_000_000) == pytest.approx(2.12)
    spend.record("b", "openai/gpt-6-luna", 1_000_000)
    spend.record("a", "codex:gpt-6-sol", 5_000_000)  # flat plan: $0
    assert spend.record("a", "x", 0) == 0.0          # zero tokens not stored
    assert spend.spent_today("a") == pytest.approx(2.12)
    assert spend.spent_today() == pytest.approx(2.23)
    assert spend.today_by_agent()["a"]["calls"] == 2


def test_budget_precedence(monkeypatch):
    monkeypatch.delenv("EEZE_BUDGET_USD_DAILY", raising=False)
    assert spend.budget_for(None) == spend.DEFAULT_BUDGET_USD_DAILY
    monkeypatch.setenv("EEZE_BUDGET_USD_DAILY", "5")
    assert spend.budget_for(Agent(id="x", name="X")) == 5.0
    assert spend.budget_for(Agent(id="x", name="X", budget_usd_daily=0.5)) == 0.5
    assert spend.budget_for(Agent(id="x", name="X", budget_usd_daily=0)) is None  # 0 = no cap


def test_check_budget_raises_at_the_cap():
    agent = Agent(id="fin", name="Fin", budget_usd_daily=1.0)
    spend.check_budget(agent)
    spend.record("fin", "openai/gpt-6-sol", 500_000)  # $1.06
    with pytest.raises(spend.BudgetExceeded) as err:
        spend.check_budget(agent)
    assert "fin" in str(err.value)


class CountingBrain:
    """Always picks the first candidate and reports 400k tokens on a paid model."""

    def __init__(self) -> None:
        self.calls = 0

    def select_element(self, ctx, *, intent, state, candidates):
        self.calls += 1
        return Judgment(kind="select_element", question=intent,
                        answer=candidates[0].id if candidates else None, confidence=0.99,
                        ms=1.0, tokens=400_000, model="openai/gpt-6-sol")

    def verify(self, ctx, *, statement, state):  # pragma: no cover - not used
        raise AssertionError


def test_loop_stops_before_spending_past_the_cap(tmp_path: Path):
    from eeze_agent.core.models import Observation

    class Driver(FakeDriver):
        def capture(self, ctx, pid, wid, screenshot=False):
            return Observation(pid=pid, window_id=wid, window_title="Fake",
                               elements=[{"role": "button", "label": "OK", "token": "t1",
                                          "element_index": 0}])

    agent = Agent(id="ops", name="Ops", budget_usd_daily=1.0)
    task = TaskSpec(name="clicky", app="Fake", steps=[
        StepSpec(id=f"c{i}", action="click", intent="press OK", retries=0, fatal=False) for i in range(5)
    ])
    brain = CountingBrain()
    journal = RunJournal(tmp_path / "runs", "rs-budget", agent_id="ops")
    summary = run_set(task=task, agent_ctx=AgentContext(agent=agent), driver=Driver(),
                      brain=brain, journal=journal, runs=1, out_dir=tmp_path / "out",
                      policy=Policy(frozenset({"read", "write_local"})))
    journal.close()
    # 400k tokens of Sol ≈ $0.85 per call: the 2nd call pushes past $1, the 3rd never happens.
    assert brain.calls == 2
    assert summary["status"] == "budget_exceeded"
    kinds = [json.loads(line)["kind"]
             for line in (tmp_path / "runs" / "rs-budget" / "journal.jsonl").read_text().splitlines()]
    assert "budget_exceeded" in kinds


def test_spend_api(tmp_path: Path):
    from eeze_agent.api.app import create_app

    home = tmp_path / "home"
    home.mkdir()
    (home / "api.token").write_text("tok", encoding="utf-8")
    client = TestClient(create_app(repo_root=tmp_path, serve_ui=False, eeze_home=home))
    assert client.post("/api/session/pair", json={"token": "tok"}).status_code == 200
    spend.record("default", "openai/gpt-6-luna", 1_000_000)
    body = client.get("/api/spend/today").json()
    row = next(a for a in body["agents"] if a["agent_id"] == "default")
    assert row["spent_usd"] == pytest.approx(0.11)
    assert row["budget_usd"] == spend.DEFAULT_BUDGET_USD_DAILY
    assert row["remaining_usd"] == pytest.approx(spend.DEFAULT_BUDGET_USD_DAILY - 0.11)
