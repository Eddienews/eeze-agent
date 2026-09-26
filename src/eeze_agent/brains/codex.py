"""Codex-subscription brain (P1, local-only): judgments through the Codex CLI.

Provider plan: ``docs/PROVIDERS-PLAN.md``. Until the product ships BYO provider keys, the
brains run on the owner's **Codex/ChatGPT subscription** — and the owner's standing rule
for this phase is **no paid spend while testing**, so this brain is *subscription-only by
default*: no OpenRouter, no Jev calls, flat plan. The CLI owns auth and token refresh
(``codex login status`` -> "Logged in using ChatGPT"); this brain only shells out to it.

Same two methods as the other brains (``select_element`` / ``verify``). Every judgment is
ONE ephemeral ``codex exec --json`` process:

* ``--ephemeral`` — thousands of judgments must not land in the user's Codex history;
* ``--sandbox read-only`` + a scratch cwd — a judgment only reads its prompt;
* ``--skip-git-repo-check`` — the scratch dir is not a repo;
* the PROMPT travels on **stdin** (``-``), never as an argument: on Windows the argv goes
  through ``cmd /c``, which mangles JSON quotes and silently drops the payload (measured
  live — the model answered the role-play instead of the question);
* stdout is a JSONL event stream; the last ``agent_message`` text is parsed with the same
  tolerant ``parse_json_object`` the LlmBrain uses, and ``turn.completed.usage`` supplies
  the token count.

Models (verified entitled on the subscription, 2026-09-24): ``gpt-6-luna`` (routine) and
``gpt-6-sol`` (hard) — the same Luna/Sol policy the paid router uses, but flat-priced. The
tier comes from the router's **free deterministic rules floor** (no Jev call: on a flat
plan the paid decision would buy nothing), and a failed run escalates routine -> hard
*inside the subscription* (``brains/registry.py``).

Failure ladder (no money by default): each judgment retries the CLI
(``EEZE_CODEX_ATTEMPTS``, default 2) and then FAILS HONESTLY — the judgment degrades to a
retry / failed check, with ``last_error`` recorded. The paid ``LlmBrain`` fallback is
**opt-in only**: ``EEZE_CODEX_FALLBACK=openrouter``. When enabled, ``Judgment.model``
records which engine answered (``codex:<model>`` vs the OpenRouter model), so neither the
journal nor the run summary lies about where a judgment came from.

Windows: the npm shim is a ``.cmd``, which CreateProcess cannot launch directly, so the
argv is built as ``cmd /c codex ...`` (``tests/test_codex_brain.py`` replays a real
captured stream).

Env: ``EEZE_CODEX_BIN`` (default ``codex``), ``EEZE_CODEX_MODEL`` (absolute pin for both
tiers), ``EEZE_CODEX_MODEL_ROUTINE`` / ``EEZE_CODEX_MODEL_HARD`` (defaults ``gpt-6-luna`` /
``gpt-6-sol``), ``EEZE_CODEX_TIMEOUT`` (default 180 s), ``EEZE_CODEX_SCRATCH``,
``EEZE_CODEX_ATTEMPTS`` (default 2), ``EEZE_CODEX_ROUTER`` (``rules`` default; ``off``
forces routine), ``EEZE_CODEX_FALLBACK`` (``none`` default; ``openrouter`` opts into paid
fallback).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from eeze_agent.agents.models import AgentContext
from eeze_agent.brains.llm import SELECT_SYSTEM, VERIFY_SYSTEM, LlmBrain, clamp01
from eeze_agent.brains.router import (
    DEFAULT_TIERS,
    RouteDecision,
    escalated_tier,
    rules_decision,
    signals_for,
)
from eeze_agent.core.jsonx import parse_json_object
from eeze_agent.core.models import Candidate, Judgment

SCRATCH_DEFAULT = Path.home() / ".eeze" / "codex-scratch"
ENGINE_PREFIX = "codex:"
MODEL_ROUTINE_DEFAULT = "gpt-6-luna"
MODEL_HARD_DEFAULT = "gpt-6-sol"
FALLBACK_ENV = "EEZE_CODEX_FALLBACK"
_CMD_META = frozenset('&|<>^%!"\n\r')


def codex_home() -> Path:
    """``$CODEX_HOME`` or ``~/.codex`` — where the CLI keeps its session."""
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def codex_model_for_tier(tier: str | None) -> str:
    """Subscription model for a router tier (env-overridable; never invented)."""
    routine = os.environ.get("EEZE_CODEX_MODEL_ROUTINE") or MODEL_ROUTINE_DEFAULT
    hard = os.environ.get("EEZE_CODEX_MODEL_HARD") or MODEL_HARD_DEFAULT
    return hard if str(tier or "").strip().lower() == "hard" else routine


def paid_fallback_enabled() -> bool:
    """The paid LlmBrain fallback is opt-in: testing must not spend money."""
    return (os.environ.get(FALLBACK_ENV) or "none").strip().lower() == "openrouter"


def escalated_tier_name(tier: str) -> str:
    """One tier up, capped at the top — delegates to the router's own ladder."""
    return escalated_tier(str(tier).strip().lower(), DEFAULT_TIERS)


def tier_for_task(task: object | None, *, escalate_from: str | None = None) -> tuple[str, str]:
    """(tier, source) from the FREE rules floor — no Jev call, no network.

    On a flat subscription every tier costs the same, so the paid Jev decision would buy
    nothing here; the deterministic rules still keep Luna for routine work and Sol for hard
    work (the agreed policy), and a failed run climbs routine -> hard for free.
    """
    if escalate_from:
        return escalated_tier_name(escalate_from), "escalated"
    if task is None or (os.environ.get("EEZE_CODEX_ROUTER") or "rules").strip().lower() == "off":
        return "routine", "rules"
    decision = rules_decision(signals_for(task), DEFAULT_TIERS)
    return decision.tier, decision.source


def build_argv(binary: str, model: str, scratch: Path, *, platform: str | None = None) -> list[str]:
    """argv for one ephemeral judgment run (``cmd /c`` prefix on Windows).

    The PROMPT travels on stdin (``-``), never as an argument: judgment payloads are JSON,
    and on Windows ``cmd /c`` mangles an argument full of double quotes — measured live, the
    model received a prompt with the whole payload missing and answered the role-play
    instead of the question.
    """
    argv = [
        binary,
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "-C",
        str(scratch),
    ]
    if model:
        from eeze_agent.core.providers import valid_model_id

        if not valid_model_id(model):
            raise ValueError("invalid codex model id")
        argv += ["-m", model]
    argv.append("-")
    if (platform or os.name) == "nt":
        # cmd.exe re-parses the line: a metacharacter in ANY argument (binary path from
        # EEZE_CODEX_BIN, scratch dir, model) would run a second command. Refuse, never escape.
        if any(ch in part for part in argv for ch in _CMD_META):
            raise ValueError("refusing a codex argument with shell metacharacters")
        return ["cmd", "/c", *argv]
    return argv


def parse_exec_jsonl(text: str) -> tuple[str | None, int]:
    """(last agent message, total tokens) from a ``codex exec --json`` stream.

    Error items (unrecognized config keys, websocket retries) and non-JSON log lines are
    skipped on purpose: the CLI interleaves them with the answer.
    """
    message: str | None = None
    tokens = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        item = event.get("item") or {}
        if kind == "item.completed" and item.get("type") == "agent_message" and item.get("text"):
            message = str(item["text"])
        elif kind == "turn.completed":
            usage = event.get("usage") or {}
            tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    return message, tokens


def codex_exec_once(
    system: str,
    user: str,
    *,
    binary: str = "codex",
    model: str = "",
    scratch: str | Path = SCRATCH_DEFAULT,
    timeout: float = 180.0,
    runner: Callable[[list[str], str], tuple[int, str]] | None = None,
) -> tuple[str, int]:
    """ONE ephemeral CLI run -> (agent text, tokens). Raises on ANY failure."""
    prompt = f"{system}\n\n{user}"
    argv = build_argv(binary, model, Path(scratch))
    if runner is not None:
        returncode, stdout = runner(argv, prompt)
    else:
        proc = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=prompt,  # stdin, not argv — JSON quotes survive Windows parsing
            cwd=str(scratch),
            timeout=timeout,
        )
        returncode, stdout = proc.returncode, proc.stdout
    if returncode != 0:
        raise RuntimeError(f"codex exec exited {returncode}")
    message, tokens = parse_exec_jsonl(stdout)
    if not message:
        raise RuntimeError("codex exec produced no agent message")
    return message, tokens


def codex_client(
    *,
    model: str | None = None,
    tier: str = "hard",
    binary: str | None = None,
    timeout: float | None = None,
    attempts: int | None = None,
    scratch: str | Path | None = None,
    runner: Callable[[list[str], str], tuple[int, str]] | None = None,
) -> Callable[[str, str], tuple[str, int]]:
    """A ``(system, user) -> (text, tokens)`` client on the subscription, for the texts that are
    not loop judgments (the planner and the spec writer). Subscription-only like the brain: it
    retries the CLI and then RAISES — no paid engine is ever reached from here."""
    resolved_binary = binary or os.environ.get("EEZE_CODEX_BIN") or "codex"
    resolved_model = model or os.environ.get("EEZE_CODEX_MODEL") or codex_model_for_tier(tier)
    resolved_scratch = Path(scratch or os.environ.get("EEZE_CODEX_SCRATCH") or SCRATCH_DEFAULT)
    resolved_scratch.mkdir(parents=True, exist_ok=True)
    resolved_timeout = float(timeout or os.environ.get("EEZE_CODEX_TIMEOUT") or 180.0)
    resolved_attempts = max(1, int(attempts or os.environ.get("EEZE_CODEX_ATTEMPTS") or 2))

    def chat(system: str, user: str) -> tuple[str, int]:
        last: Exception | None = None
        for _ in range(resolved_attempts):
            try:
                return codex_exec_once(
                    system,
                    user,
                    binary=resolved_binary,
                    model=resolved_model,
                    scratch=resolved_scratch,
                    timeout=resolved_timeout,
                    runner=runner,
                )
            except Exception as exc:  # noqa: BLE001 — a failure is a retry, then an honest raise
                last = exc
        raise RuntimeError(
            f"codex engine failed after {resolved_attempts} attempts: {type(last).__name__}: {last}"
        )

    chat.model = resolved_model  # type: ignore[attr-defined]  # truthful attribution for callers
    return chat


class CodexBrain:
    """Judgments on the Codex subscription — subscription-only unless paid fallback is opted in."""

    def __init__(
        self,
        *,
        binary: str | None = None,
        model: str | None = None,
        tier: str | None = None,
        timeout: float | None = None,
        scratch: str | Path | None = None,
        attempts: int | None = None,
        route_source: str | None = None,
        fallback: object | None = None,
        fallback_chat: Callable[[str, str], tuple[str, int]] | None = None,
        runner: Callable[[list[str], str], tuple[int, str]] | None = None,
    ) -> None:
        self.binary = binary or os.environ.get("EEZE_CODEX_BIN") or "codex"
        self.tier = "hard" if str(tier or "").strip().lower() == "hard" else "routine"
        pinned = model or os.environ.get("EEZE_CODEX_MODEL")
        self.model = pinned or codex_model_for_tier(self.tier)
        self.timeout = float(timeout or os.environ.get("EEZE_CODEX_TIMEOUT") or 180.0)
        self.attempts = max(1, int(attempts or os.environ.get("EEZE_CODEX_ATTEMPTS") or 2))
        self.scratch = Path(scratch or os.environ.get("EEZE_CODEX_SCRATCH") or SCRATCH_DEFAULT)
        self.scratch.mkdir(parents=True, exist_ok=True)
        if fallback is not None:
            self.fallback: object | None = fallback
        elif paid_fallback_enabled():
            self.fallback = LlmBrain()
        else:
            self.fallback = None
        self._fallback_chat = fallback_chat or (
            lambda system, user: self.fallback._chat(system, user)  # type: ignore[union-attr]
        )
        self._runner = runner  # tests: (argv, prompt) -> (returncode, stdout)
        self.engine = f"{ENGINE_PREFIX}{self.model}"
        ladder = "paid fallback opted in" if self.fallback is not None else "subscription-only"
        self.route = RouteDecision(
            tier=self.tier,
            model=self.engine,
            source=route_source or ("pin" if pinned else "rules"),
            reason=f"Codex subscription ({self.tier} -> {self.model}; {ladder})",
        )
        self.calls = 0
        self.fallbacks = 0
        self.last_error: str | None = None

    # -- transport -----------------------------------------------------------

    def _exec(self, system: str, user: str) -> tuple[str, int]:
        """One ephemeral CLI run. Raises on any failure (the caller retries/falls back)."""
        self.calls += 1
        return codex_exec_once(
            system,
            user,
            binary=self.binary,
            model=self.model,
            scratch=self.scratch,
            timeout=self.timeout,
            runner=self._runner,
        )

    def _reply(self, system: str, user: str) -> tuple[str, int, str]:
        """(text, tokens, engine) — subscription retries first, paid brain only if opted in."""
        last: Exception | None = None
        for _ in range(self.attempts):
            try:
                text, tokens = self._exec(system, user)
                return text, tokens, self.engine
            except Exception as exc:  # noqa: BLE001 — a failure is a retry, never a crash
                last = exc
        self.last_error = f"{type(last).__name__}: {last}"[:200]
        if self.fallback is None:
            raise RuntimeError(f"codex engine failed after {self.attempts} attempts: {self.last_error}")
        self.fallbacks += 1
        text, tokens = self._fallback_chat(system, user)
        return text, tokens, str(getattr(self.fallback, "model", "fallback"))

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
                "candidates": [{"id": c.id, "element": c.describe()} for c in candidates],
                "none_match": "No candidate is the right element for this step",
                "ui_state": state,
            },
            ensure_ascii=False,
            default=str,
        )[:16000]
        t0 = time.perf_counter()
        try:
            reply, tokens, engine = self._reply(SELECT_SYSTEM, user)
            parsed = parse_json_object(reply, what="codex brain reply")
            answer = parsed.get("answer")
            answer = str(answer) if answer is not None else None
            confidence = clamp01(parsed.get("confidence"))
        except Exception:  # noqa: BLE001 — a failed judgment is a retry, never a crash
            tokens, engine, answer, confidence = 0, self.engine, None, None
        ms = (time.perf_counter() - t0) * 1000
        return Judgment(
            kind="select_element",
            question=intent,
            answer=answer,
            confidence=confidence,
            probabilities=None,
            ms=round(ms, 1),
            tokens=tokens,
            model=engine,
            request_id=None,
        )

    def verify(self, ctx: AgentContext, *, statement: str, state: dict) -> Judgment:
        user = json.dumps({"statement": statement, "ui_state": state}, ensure_ascii=False, default=str)[
            :16000
        ]
        t0 = time.perf_counter()
        try:
            reply, tokens, engine = self._reply(VERIFY_SYSTEM, user)
            parsed = parse_json_object(reply, what="codex brain reply")
            noul = clamp01(parsed.get("probability"))
        except Exception:  # noqa: BLE001 — a failed check fails the threshold, never crashes
            tokens, engine, noul = 0, self.engine, None
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
            model=engine,
            request_id=None,
        )
