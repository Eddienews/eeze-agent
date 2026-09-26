"""Jev brain — typed judgments through TypeSafe System One.

The loop asks one batched question per cycle; code owns the workflow and Jev
answers closed-set judgments (see docs/ARCHITECTURE.md and the F0/F1 findings).
Every method receives the run's ``AgentContext`` (ADR-0002); F1 records the agent
id downstream, and later revisions can scope instructions per agent role.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from eeze_agent.agents.models import AgentContext
from eeze_agent.core.models import Candidate, Judgment

PRICE_PER_MTOK_INPUT = 0.042  # USD per million input tokens (jev, Sep 2026)


def _ensure_env() -> None:
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    from dotenv import load_dotenv

    for candidate in (
        Path(__file__).resolve().parents[2] / ".env",  # repo root
        Path.cwd() / ".env",
    ):
        if candidate.exists():
            load_dotenv(candidate)
            return


class JevBrain:
    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        _ensure_env()
        if client is None:
            from typesafe_sdk import TypeSafeClient

            client = TypeSafeClient(model=model) if model else TypeSafeClient()
        self.client = client

    # -- judgments -----------------------------------------------------------
    def select_element(
        self,
        ctx: AgentContext,
        *,
        intent: str,
        state: dict,
        candidates: list[Candidate],
    ) -> Judgment:
        """Choice over code-enumerated candidates (+ ``none_match``)."""
        from typesafe_sdk import Choice

        criteria: dict[str, str] = {c.id: c.describe() for c in candidates}
        criteria["none_match"] = "No candidate is the right element for this step"
        question = Choice(instructions=intent, criteria=criteria)
        return self._ask(
            ctx, state=state, questions={"select": question}, kind="select_element", qid="select"
        )

    def verify(self, ctx: AgentContext, *, statement: str, state: dict) -> Judgment:
        """Noul — probability that the statement holds for the observed state."""
        from typesafe_sdk import Noul

        question = Noul(instructions=statement)
        return self._ask(
            ctx, state=state, questions={"check": question}, kind="verify", qid="check"
        )

    # -- internals -----------------------------------------------------------
    def _ask(
        self,
        ctx: AgentContext,
        *,
        state: dict,
        questions: dict,
        kind: str,
        qid: str,
    ) -> Judgment:
        t0 = time.perf_counter()
        resp = self.client.system_one(state=state, questions=questions)
        ms = (time.perf_counter() - t0) * 1000
        answer = resp.answers[qid]
        usage = getattr(resp, "usage", None)
        return Judgment(
            kind=kind,
            question=str(getattr(questions[qid], "instructions", "")),
            answer=getattr(answer, "choice", None) if kind == "select_element" else None,
            confidence=getattr(answer, "confidence", None),
            probabilities=getattr(answer, "probabilities", None),
            noul=getattr(answer, "noul", None) if kind == "verify" else None,
            ms=round(ms, 1),
            tokens=int(getattr(usage, "input_tokens", 0) or 0),
            model=getattr(resp, "model", None),
            request_id=getattr(resp, "request_id", None),
        )
