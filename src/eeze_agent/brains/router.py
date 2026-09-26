"""Model router (v2): Luna for routine work, Sol for hard work.

Policy (founder, 2026-09-23): DeepSeek is retired; two tiers —

    routine -> ``openai/gpt-6-luna``  (~$0.00025 per select+verify cycle, measured)
    hard    -> ``openai/gpt-6-sol``   (~$0.0047 per cycle, measured)

Decision order (first match wins):

1. an explicit model pin (``make_brain(model=...)`` or ``EEZE_BRAIN_MODEL``) — never routed;
2. ``agents.yaml`` -> ``model.tier`` (a tier forced for that agent);
3. an escalation (the previous run of this runset FAILED): one tier up, deterministic;
4. Jev, as a typed ``Choice`` over the tier set (live probe 4/4 correct: 137-349 ms,
   ~550 tokens, ~$0.000023 per decision);
5. the rules floor — deterministic signals (goal text, app, step kinds) — also the
   fallback whenever Jev errors, refuses, or answers below ``JEVI_CONFIDENCE_FLOOR``.

Every decision is journaled as ``model_route`` (tier, model, source, reason, confidence,
ms, tokens) — never silent. ``EEZE_ROUTER=off`` restores the plain env model.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

TIERS: tuple[str, ...] = ("routine", "hard")

DEFAULT_TIERS: dict[str, str] = {
    "routine": "openai/gpt-6-luna",
    "hard": "openai/gpt-6-sol",
}

JEVI_CONFIDENCE_FLOOR = 0.6

# GUI steps up to this size default to the cheap tier; larger flows go hard. A policy
# guess, not a law — the escalation ladder is the safety net (2026-09-23).
SMALL_GUI_STEPS = 5

TIER_BLURB: dict[str, str] = {
    "routine": (
        "cheapest; for routine, high-volume, low-ambiguity work: mailbox/attachment "
        "extraction, single-form fills, short script-driven repeats"
    ),
    "hard": (
        "strongest computer-use and coding; for hard work: multi-window GUI workflows, "
        "goal planning and replanning, authoring strict video/3D scene specs"
    ),
}

# Word-boundary markers over the task's searchable text (name + app + step ids/intents).
HARD_MARKERS: tuple[str, ...] = (
    "blender",
    "3d",
    "render",
    "video",
    "ffmpeg",
    "montage",
    "timeline",
    "scene",
    "spec",
    "replan",
    "complex",
    "multi-window",
)
ROUTINE_MARKERS: tuple[str, ...] = (
    "invoice",
    "invoices",
    "inbox",
    "mail",
    "mailbox",
    "imap",
    "attachment",
    "attachments",
    "extract",
    "ledger",
    "csv",
    "download",
    "parse",
    "pull",
)

POLICY_PROMPT = (
    "Pick the model tier that should handle this task. Policy: the cheapest tier that can "
    "do the job CORRECTLY; when correctness is at risk, prefer the stronger tier. "
    "Task: {summary}"
)


class RouterRefusal(RuntimeError):
    """Jev answered with something unusable (non-tier choice or low confidence)."""


@dataclass(frozen=True)
class TaskSignals:
    """What the router is allowed to see about a task (bounded, no secrets)."""

    name: str
    app: str
    text: str  # lowercased searchable text (rules markers)
    gui_steps: int  # steps that need element judgments
    script_steps: int
    summary: str  # raw concatenation, bounded
    prose: str = ""  # decision-shaped description (what Jev actually reads)


@dataclass(frozen=True)
class RouteDecision:
    tier: str
    model: str
    source: str  # pin | config | escalated | jev | rules | rules-fallback
    reason: str
    confidence: float | None = None
    ms: float | None = None
    tokens: int | None = None

    def as_event(self) -> dict:
        return {
            "tier": self.tier,
            "model": self.model,
            "source": self.source,
            "reason": self.reason,
            "confidence": self.confidence,
            "ms": self.ms,
            "tokens": self.tokens,
        }


# -- configuration ------------------------------------------------------------


def router_mode() -> str:
    """``jev`` (default) decides with a rules fallback; ``rules`` never calls Jev; ``off``
    disables routing entirely (the caller then leaves the brain on its env model)."""
    return (os.environ.get("EEZE_ROUTER") or "jev").strip().lower()


def tiers_for(
    agent_id: str = "default", repo_root: Path | None = None, provider_id: str | None = None
) -> dict[str, str]:
    """Tier -> model: built-in defaults, then the ACTIVE provider's own models, then ``agents.yaml``
    -> ``model.tiers`` (the most specific layer wins).

    The provider layer (P3) only fills a tier with a NON-empty model: a provider whose models were
    never measured (openai, google, xai, groq, ollama — empty catalog on purpose) keeps the built-in
    names instead of routing to an invented id. The Settings screen is where the user sets them.
    """
    tiers = dict(DEFAULT_TIERS)
    if provider_id:
        tiers.update(_provider_tiers(provider_id))
    model = _agent_model(agent_id, repo_root)
    configured = model.get("tiers")
    if isinstance(configured, dict):
        for tier, value in configured.items():
            if str(tier) in TIERS and value:
                tiers[str(tier)] = str(value)
    return tiers


def _provider_tiers(provider_id: str) -> dict[str, str]:
    """The active provider's routine/hard models (store override or measured catalog default)."""
    from eeze_agent.core.providers import tier_models

    try:
        models = tier_models(provider_id)
    except ValueError:  # unknown provider id -> keep the defaults, never guess
        return {}
    return {tier: model for tier, model in models.items() if tier in TIERS and model}


def forced_tier(agent_id: str = "default", repo_root: Path | None = None) -> str | None:
    """A tier forced for this agent by ``agents.yaml`` -> ``model.tier``."""
    value = _agent_model(agent_id, repo_root).get("tier")
    value = str(value) if value else None
    return value if value in TIERS else None


def _agent_model(agent_id: str, repo_root: Path | None) -> dict:
    if repo_root is None:
        return {}
    try:
        from eeze_agent.agents.registry import load_registry

        agent = load_registry(repo_root).get(agent_id)
    except (KeyError, OSError):
        return {}
    model = getattr(agent, "model", None)
    if isinstance(model, dict):
        return model
    return {key: getattr(model, key, None) for key in ("brain", "tier", "tiers")}


def tier_of(model: str, tiers: dict[str, str]) -> str:
    """The tier a concrete model id belongs to (used for pins)."""
    for tier, candidate in tiers.items():
        if candidate == model:
            return tier
    return "pinned"


def escalated_tier(tier: str, tiers: dict[str, str]) -> str:
    """One tier up from ``tier``, capped at the top tier."""
    order = [t for t in TIERS if t in tiers]
    if tier not in order:
        return order[0] if order else "routine"
    index = min(order.index(tier) + 1, len(order) - 1)
    return order[index]


# -- signals ------------------------------------------------------------------


def signals_for(task: object) -> TaskSignals:
    """Build router signals from a ``TaskSpec`` (or a plain goal string)."""
    if isinstance(task, str):
        text = task.strip()
        return TaskSignals(
            name="<goal>", app="", text=text.lower(), gui_steps=0, script_steps=0,
            summary=text[:600], prose=text[:600],
        )
    name = str(getattr(task, "name", "") or "")
    app = str(getattr(task, "app", "") or "")
    parts: list[str] = [name, app]
    gui = script = 0
    for step in getattr(task, "steps", []) or []:
        parts.append(str(getattr(step, "id", "") or ""))
        intent = str(getattr(step, "intent", "") or "")
        if intent:
            parts.append(intent)
        if getattr(step, "command", None):
            script += 1
            parts.append(str(step.command)[:160])
        else:
            gui += 1
    text = " ".join(parts)
    # Decision-shaped prose for Jev (measured 2026-09-23: raw concatenation made a
    # script-only task look "hard" 0.63-0.75; with the step counts in prose it answered
    # routine at 0.77-0.86 — the counts are the fact it actually needs).
    head = f"Task '{name or '<task>'}'"
    if app:
        head += f" in app '{app}'"
    head += f" — {gui} GUI steps, {script} script steps"
    return TaskSignals(
        name=name or "<task>",
        app=app,
        text=text.lower(),
        gui_steps=gui,
        script_steps=script,
        summary=text[:600],
        prose=(head + ": " + text[:420])[:600],
    )


def _matches(markers: tuple[str, ...], text: str) -> list[str]:
    return [m for m in markers if re.search(rf"\b{re.escape(m)}\b", text, re.IGNORECASE)]


# -- decisions ----------------------------------------------------------------


def rules_decision(
    signals: TaskSignals, tiers: dict[str, str], *, escalate_from: str | None = None
) -> RouteDecision:
    """The deterministic floor: no network, no model, same answer every time."""
    if escalate_from:
        tier = escalated_tier(escalate_from, tiers)
        return RouteDecision(
            tier=tier,
            model=tiers[tier],
            source="escalated",
            reason=f"previous run failed at tier {escalate_from!r}",
        )
    if signals.script_steps and not signals.gui_steps:
        # No brain calls happen at all — the tier is reported, never billed.
        return RouteDecision(
            tier="routine", model=tiers["routine"], source="rules",
            reason="script-only task (no GUI judgments — tier unused)",
        )
    hard_hits = _matches(HARD_MARKERS, signals.text)
    if hard_hits:
        return RouteDecision(
            tier="hard", model=tiers["hard"], source="rules",
            reason=f"hard markers: {', '.join(hard_hits[:4])}",
        )
    routine_hits = _matches(ROUTINE_MARKERS, signals.text)
    if routine_hits:
        return RouteDecision(
            tier="routine", model=tiers["routine"], source="rules",
            reason=f"routine markers: {', '.join(routine_hits[:4])}",
        )
    if signals.gui_steps <= SMALL_GUI_STEPS:
        return RouteDecision(
            tier="routine", model=tiers["routine"], source="rules",
            reason=f"small GUI task ({signals.gui_steps} GUI steps) — cheapest first",
        )
    return RouteDecision(
        tier="hard", model=tiers["hard"], source="rules",
        reason=f"large GUI workflow ({signals.gui_steps} GUI steps)",
    )


def jev_decision(signals: TaskSignals, tiers: dict[str, str], *, client: object | None = None) -> RouteDecision:
    """Ask Jev: a typed Choice over the tier set. Raises on anything unusable."""
    from typesafe_sdk import Choice, TypeSafeClient

    from eeze_agent.brains.jev import _ensure_env

    _ensure_env()
    if client is None:
        client = TypeSafeClient()
    criteria = {tier: f"{tiers[tier]} — {TIER_BLURB[tier]}" for tier in TIERS if tier in tiers}
    criteria["none_match"] = "Neither tier fits this task"
    question = Choice(
        instructions=POLICY_PROMPT.format(summary=signals.prose or signals.summary),
        criteria=criteria,
    )
    t0 = time.perf_counter()
    response = client.system_one(
        state={"task": signals.prose or signals.summary}, questions={"route": question}
    )
    ms = (time.perf_counter() - t0) * 1000
    answer = response.answers["route"]
    tier = getattr(answer, "choice", None)
    confidence = getattr(answer, "confidence", None)
    usage = getattr(response, "usage", None)
    tokens = int(getattr(usage, "input_tokens", 0) or 0)
    if tier not in tiers:
        raise RouterRefusal(f"jev chose {tier!r}, which is not one of {sorted(tiers)}")
    if confidence is not None and float(confidence) < JEVI_CONFIDENCE_FLOOR:
        raise RouterRefusal(f"jev confidence {confidence} below floor {JEVI_CONFIDENCE_FLOOR}")
    return RouteDecision(
        tier=str(tier),
        model=tiers[str(tier)],
        source="jev",
        reason=f"jev chose {tier!r} (confidence {confidence})",
        confidence=float(confidence) if confidence is not None else None,
        ms=round(ms, 1),
        tokens=tokens,
    )


def route_task(
    task: object,
    *,
    agent_id: str = "default",
    repo_root: Path | None = None,
    pin: str | None = None,
    escalate_from: str | None = None,
    jev_client: object | None = None,
    provider_id: str | None = None,
) -> RouteDecision:
    """Decide the model for one run of ``task`` (see the module docstring for the order)."""
    tiers = tiers_for(agent_id, repo_root, provider_id)
    signals = signals_for(task)
    if pin:
        return RouteDecision(
            tier=tier_of(pin, tiers), model=pin, source="pin",
            reason="explicit model pin — the router does not override it",
        )
    forced = forced_tier(agent_id, repo_root)
    if forced:
        return RouteDecision(
            tier=forced, model=tiers[forced], source="config",
            reason=f"agents.yaml forces model.tier={forced}",
        )
    if escalate_from:
        return rules_decision(signals, tiers, escalate_from=escalate_from)
    if router_mode() == "jev":
        try:
            return jev_decision(signals, tiers, client=jev_client)
        except Exception as exc:  # noqa: BLE001 — routing must never block a run
            fallback = rules_decision(signals, tiers)
            return RouteDecision(
                tier=fallback.tier,
                model=fallback.model,
                source="rules-fallback",
                reason=f"jev unavailable ({type(exc).__name__}: {str(exc)[:120]}) -> {fallback.reason}",
            )
    return rules_decision(signals, tiers)
