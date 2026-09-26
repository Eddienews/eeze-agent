"""LLM brain (v2): the loop's judgments through any OpenAI-compatible endpoint.

Same two methods as JevBrain — ``select_element`` and ``verify`` — so brains are
swappable per agent (`agents.yaml` → ``model.brain``) or globally (`EEZE_BRAIN`).
Slower and less calibrated than Jev's typed judgments; use where vendor flexibility
or cost matters. The loop's confidence thresholds still apply — an LLM that cannot
express calibrated uncertainty will retry more, never bypass the gate.

Env (defaults fall back to the planner's OpenRouter settings):
    EEZE_BRAIN_BASE_URL / EEZE_BRAIN_API_KEY / EEZE_BRAIN_MODEL
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from eeze_agent.agents.models import AgentContext
from eeze_agent.core.jsonx import parse_json_object
from eeze_agent.core.models import Candidate, Judgment

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# Router-era default (2026-09-23): DeepSeek retired; this is the fallback for runs the
# router never saw (see brains/router.py — routine Luna / hard Sol, Jev deciding).
DEFAULT_MODEL = "openai/gpt-6-luna"

SELECT_SYSTEM = """You are the tactical selector of Eeze, a computer-use agent driving Windows
GUI apps in the background. You receive a UI state and a list of candidate elements; pick
the ONE candidate that best fulfills the instruction. Answer with ONLY a JSON object:
{"answer": "<candidate id>", "confidence": <0..1>}
- "answer" MUST be one of the given candidate ids or exactly "none_match".
- "confidence" is your calibrated probability that the pick is correct.
No prose, no markdown."""

VERIFY_SYSTEM = """You are the verifier of Eeze, a computer-use agent. Given the UI state and a
statement, estimate the probability (0..1) that the statement is TRUE for this exact state
(not that it will become true). Answer with ONLY a JSON object:
{"probability": <0..1>, "reason": "<one short sentence>"}
No prose, no markdown."""


def clamp01(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


class LlmBrain:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        client: Callable[[str, str], str] | None = None,
        provider: object | None = None,
    ) -> None:
        # Provider layer (P2, core/providers.py): a stored key/endpoint beats env beats the
        # built-in default. An explicit argument still wins over everything (run override).
        cfg = provider
        if cfg is None:
            from eeze_agent.core.providers import resolve_provider

            cfg = resolve_provider("brain")
        from eeze_agent.core.providers import require_key_for_endpoint_override

        require_key_for_endpoint_override(base_url, api_key, cfg)
        self.provider_id = getattr(cfg, "provider_id", "") or "openrouter"
        self.provider_source = getattr(cfg, "source", "default")
        self.base_url = (
            base_url
            or getattr(cfg, "base_url", "")
            or os.environ.get("EEZE_BRAIN_BASE_URL")
            or os.environ.get("EEZE_PLANNER_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = (
            api_key
            or getattr(cfg, "api_key", "")
            or ""
        )
        self.model = (
            model
            or getattr(cfg, "model", "")
            or os.environ.get("EEZE_BRAIN_MODEL")
            or os.environ.get("EEZE_PLANNER_MODEL")
            or DEFAULT_MODEL
        )
        self.timeout = timeout
        self._client = client
        self.calls = 0

    # -- transport -----------------------------------------------------------

    def _chat(self, system: str, user: str) -> tuple[str, int]:
        self.calls += 1
        if self._client is not None:
            return self._client(system, user), 0
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
        )
        if response.status_code != 200:
            raise RuntimeError(f"llm brain HTTP {response.status_code}: {response.text[:300]}")
        body = response.json()
        try:
            reply = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"llm brain reply missing choices: {str(body)[:200]}") from exc
        usage = body.get("usage") or {}
        tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        return reply, tokens

    # -- judgments -----------------------------------------------------------

    def select_element(
        self,
        ctx: AgentContext,
        *,
        intent: str,
        state: dict,
        candidates: list[Candidate],
    ) -> Judgment:
        user = json.dumps(
            {
                "instruction": intent,
                "candidates": [
                    {"id": c.id, "element": c.describe()} for c in candidates
                ],
                "none_match": "No candidate is the right element for this step",
                "ui_state": state,
            },
            ensure_ascii=False,
            default=str,
        )[:16000]
        t0 = time.perf_counter()
        try:
            reply, tokens = self._chat(SELECT_SYSTEM, user)
            parsed = parse_json_object(reply, what="llm brain reply")
            answer = parsed.get("answer")
            answer = str(answer) if answer is not None else None
            confidence = clamp01(parsed.get("confidence"))
        except Exception:  # noqa: BLE001 — a failed judgment is a retry, never a crash
            reply, tokens, answer, confidence = "", 0, None, None
        ms = (time.perf_counter() - t0) * 1000
        return Judgment(
            kind="select_element",
            question=intent,
            answer=answer,
            confidence=confidence,
            probabilities=None,
            ms=round(ms, 1),
            tokens=tokens,
            model=self.model,
            request_id=None,
        )

    def verify(self, ctx: AgentContext, *, statement: str, state: dict) -> Judgment:
        user = json.dumps({"statement": statement, "ui_state": state}, ensure_ascii=False, default=str)[:16000]
        t0 = time.perf_counter()
        try:
            reply, tokens = self._chat(VERIFY_SYSTEM, user)
            parsed = parse_json_object(reply, what="llm brain reply")
            noul = clamp01(parsed.get("probability"))
        except Exception:  # noqa: BLE001 — a failed judgment fails the check (threshold), never crashes
            reply, tokens, noul = "", 0, None
        ms = (time.perf_counter() - t0) * 1000
        return Judgment(
            kind="verify",
            question=statement,
            answer=None,
            confidence=None,
            probabilities=None,
            noul=noul,
            ms=round(ms, 1),
            tokens=tokens,
            model=self.model,
            request_id=None,
        )
