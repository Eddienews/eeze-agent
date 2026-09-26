"""Brain resolution (v2): swappable tactical brains, Jev by default.

Order of precedence:
1. explicit ``name`` argument,
2. ``EEZE_BRAIN`` env,
3. ``agents.yaml`` → the agent's ``model.brain``,
4. ``"jev"``.

Names: ``jev`` (TypeSafe, typed judgments — default) · ``llm`` (any OpenAI-compatible
endpoint; see ``brains/llm.py`` for its env vars) · ``codex`` (the owner's Codex/ChatGPT
subscription through the local CLI — local-only, subscription-only by default, free
routine/hard tiers; see ``brains/codex.py``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

VALID_BRAINS = ("jev", "llm", "codex")


def _agent_brain(agent_id: str, repo_root: Path | None) -> str | None:
    if repo_root is None:
        return None
    try:
        from eeze_agent.agents.registry import load_registry

        agent = load_registry(repo_root).get(agent_id)
    except (KeyError, OSError):
        return None
    model = getattr(agent, "model", None)
    if isinstance(model, dict):
        value = model.get("brain")
    else:
        value = getattr(model, "brain", None)
    return str(value) if value else None


def resolve_brain_name(*, name: str | None = None, agent_id: str = "default", repo_root: Path | None = None) -> str:
    """Which loop brain runs: name arg > the provider chosen in the app > ``EEZE_BRAIN`` >
    ``agents.yaml`` -> ``model.brain`` > ``jev``.

    The provider step (P3) is what makes "Use this one" on the Settings screen real: an API
    provider means the ``llm`` brain, the local subscription means ``codex``. It only exists once
    the user picks one, so an untouched install resolves exactly as before.
    """
    from eeze_agent.core.providers import default_provider_brain

    resolved = (
        name
        or default_provider_brain()
        or os.environ.get("EEZE_BRAIN")
        or _agent_brain(agent_id, repo_root)
        or "jev"
    )
    resolved = resolved.strip().lower()
    if resolved not in VALID_BRAINS:
        raise ValueError(f"unknown brain {resolved!r} — valid: {', '.join(VALID_BRAINS)}")
    return resolved


def make_brain(
    *,
    name: str | None = None,
    agent_id: str = "default",
    repo_root: Path | None = None,
    task: object | None = None,
    escalate_from: str | None = None,
    **kwargs: Any,
):
    """Build the loop brain for an agent (kwargs forwarded to the brain constructor).

    When the agent's brain is ``llm`` and a ``task`` (or goal string) is given, the MODEL
    comes from the router (`brains/router.py`: Luna routine / Sol hard, Jev deciding with a
    rules floor) and the decision rides on ``brain.route`` for the journal. An explicit
    ``model=`` kwarg or ``EEZE_BRAIN_MODEL`` is a pin the router never overrides.

    The ``codex`` brain runs subscription-only by default (the owner's testing rule: no paid
    spend): the tier comes from the router's FREE rules floor and picks the subscription
    model (``gpt-6-luna`` routine / ``gpt-6-sol`` hard), and a FAILED codex run
    (``escalate_from``) climbs routine -> hard *inside the subscription*. The paid fallback
    (OpenRouter) is opt-in via ``EEZE_CODEX_FALLBACK=openrouter``.
    """
    resolved = resolve_brain_name(name=name, agent_id=agent_id, repo_root=repo_root)
    if resolved == "llm":
        return _routed_llm(
            task=task, agent_id=agent_id, repo_root=repo_root, escalate_from=escalate_from, kwargs=kwargs
        )
    if resolved == "codex":
        from eeze_agent.brains.codex import CodexBrain, tier_for_task

        tier, source = tier_for_task(task, escalate_from=escalate_from)
        return CodexBrain(tier=tier, route_source=source, **kwargs)
    from eeze_agent.brains.jev import JevBrain, _ensure_env

    if name is None:
        _ensure_env()
        if not os.environ.get("TYPESAFE_API_KEY"):
            # Jev is optional: without a TypeSafe key, use the AI provider chosen in the app.
            # (Script-only missions — files, video, photo, 3D — never ask the brain anything.)
            return _routed_llm(
                task=task, agent_id=agent_id, repo_root=repo_root, escalate_from=escalate_from, kwargs=kwargs
            )
    return JevBrain(**kwargs)


def _routed_llm(
    *,
    task: object | None,
    agent_id: str,
    repo_root: Path | None,
    escalate_from: str | None,
    kwargs: dict[str, Any],
):
    """The ``llm`` brain; the router decides the model whenever a task is in play."""
    from eeze_agent.brains.llm import LlmBrain
    from eeze_agent.brains.router import route_task, router_mode
    from eeze_agent.core.providers import resolve_provider

    # The provider layer travels with the brain: a key stored on the Settings screen (or a chosen
    # provider) is what runs use, and the router picks tiers from THAT provider's models.
    provider = resolve_provider("brain")
    explicit = kwargs.get("model") or os.environ.get("EEZE_BRAIN_MODEL")
    if task is not None and not explicit and router_mode() != "off":
        decision = route_task(
            task,
            agent_id=agent_id,
            repo_root=repo_root,
            escalate_from=escalate_from,
            provider_id=provider.provider_id,
        )
        brain = LlmBrain(model=decision.model, provider=provider, **kwargs)
        brain.route = decision
        return brain
    return LlmBrain(provider=provider, **kwargs)
