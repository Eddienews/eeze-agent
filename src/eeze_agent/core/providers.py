"""Provider registry (P2): which endpoints, keys and models a brain may use — and where each
value came from.

The product is self-hosted and local-first: the user picks a provider, pastes their own key and
Eeze keeps it on this machine (``core/secrets_local.py``). This module owns the policy:

* the **catalog** of providers Eeze knows how to talk to, with the honesty rules the rest of the
  project follows — ``default_models`` is filled ONLY where a model was measured live on this
  machine (OpenRouter: ``openai/gpt-6-luna|sol``; Codex subscription: ``gpt-6-luna|sol``); every
  other provider ships with NO invented model id and the API must ask for one;
* ``compatible=False`` marks a documented provider that does NOT speak the OpenAI
  chat-completions the ``llm`` brain uses (Anthropic's Messages API) — selecting it is refused
  with a reason, never a fake success;
* ``local_only=True`` marks the Codex subscription: it resolves through the local CLI session and
  is never a product default (ToS);
* ``resolve_provider()`` — precedence **run arg -> agent -> store -> env -> built-in default**,
  returning a ``ProviderConfig`` whose ``sources`` say, per field, which layer supplied it. Env
  still works (headless/CLI parity); the store is the product path and beats env.

The brain NAME is not decided here (``brains/registry.py``: name arg > ``EEZE_BRAIN`` >
agents.yaml > jev); this layer fills the endpoint/key/model of the engine already chosen, and
``ProviderConfig.brain`` says which engine the provider implies (``llm`` vs ``codex``).
"""

from __future__ import annotations

import ipaddress
import os
import time
from urllib.parse import urlsplit
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from eeze_agent.core.secrets_local import SecretStore

ROLES = ("brain", "planner", "spec")
TIERS = ("routine", "hard")
DEFAULT_PROVIDER_ID = "openrouter"

# Ordered env prefixes per role — mirrors what the brains read today (llm.py / planner.py /
# specwriter.py), so resolving through this module never breaks a headless/CLI invocation.
ENV_PREFIXES: dict[str, tuple[str, ...]] = {
    "brain": ("EEZE_BRAIN", "EEZE_PLANNER"),
    "planner": ("EEZE_PLANNER",),
    "spec": ("EEZE_SPEC", "EEZE_PLANNER"),
}


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: str  # "api_key" | "oauth_external" | "local"
    base_url: str
    docs_url: str
    default_models: dict[str, str] = field(default_factory=dict)
    compatible: bool = True
    local_only: bool = False
    note: str = ""


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    base_url: str
    api_key: str
    model: str
    source: str  # which layer selected the PROVIDER: run|agent|store|env|default
    brain: str  # which engine this provider implies: "llm" | "codex"
    sources: dict[str, str] = field(default_factory=dict)  # per field: base_url/api_key/model
    note: str = ""


CATALOG: tuple[Provider, ...] = (
    Provider(
        id="openrouter",
        label="OpenRouter",
        kind="api_key",
        base_url="https://openrouter.ai/api/v1",
        docs_url="https://openrouter.ai/docs",
        default_models={"routine": "openai/gpt-6-luna", "hard": "openai/gpt-6-sol"},
        note="measured here 2026-09-23 (Luna routine / Sol hard)",
    ),
    Provider(
        id="openai",
        label="OpenAI",
        kind="api_key",
        base_url="https://api.openai.com/v1",
        docs_url="https://platform.openai.com/docs",
        note="no model default shipped — set a model before probing",
    ),
    Provider(
        id="google",
        label="Google Gemini (OpenAI-compatible endpoint)",
        kind="api_key",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        docs_url="https://ai.google.dev/gemini-api/docs/openai",
        note="no model default shipped — set a model before probing",
    ),
    Provider(
        id="xai",
        label="xAI (Grok)",
        kind="api_key",
        base_url="https://api.x.ai/v1",
        docs_url="https://docs.x.ai",
        note="no model default shipped — set a model before probing",
    ),
    Provider(
        id="groq",
        label="Groq",
        kind="api_key",
        base_url="https://api.groq.com/openai/v1",
        docs_url="https://console.groq.com/docs",
        note="no model default shipped — set a model before probing",
    ),
    Provider(
        id="ollama",
        label="Ollama (local server)",
        kind="local",
        base_url="http://127.0.0.1:11434/v1",
        docs_url="https://ollama.com",
        note="no key needed — start the server and run Test connection",
    ),
    Provider(
        id="anthropic",
        label="Anthropic",
        kind="api_key",
        base_url="https://api.anthropic.com/v1",
        docs_url="https://docs.anthropic.com",
        compatible=False,
        note="native Messages API — the llm brain speaks chat-completions; not wired yet",
    ),
    Provider(
        id="codex",
        label="Codex subscription (local CLI)",
        kind="oauth_external",
        base_url="",
        docs_url="https://developers.openai.com/codex",
        default_models={"routine": "gpt-6-luna", "hard": "gpt-6-sol"},
        local_only=True,
        note="the local Codex CLI session (~/.codex/auth.json); no API key; local-only",
    ),
)
_BY_ID: dict[str, Provider] = {p.id: p for p in CATALOG}


def provider_ids() -> list[str]:
    return [p.id for p in CATALOG]


def get_provider(provider_id: str) -> Provider:
    key = (provider_id or "").strip().lower()
    if key not in _BY_ID:
        raise ValueError(f"unknown provider {provider_id!r} — valid: {', '.join(provider_ids())}")
    return _BY_ID[key]


def codex_status() -> dict[str, Any]:
    """CLI presence + local subscription session. No subprocess, no network."""
    from shutil import which

    from eeze_agent.brains.codex import codex_home

    binary = os.environ.get("EEZE_CODEX_BIN") or "codex"
    session = (codex_home() / "auth.json").exists()
    return {"cli": bool(which(binary)), "session": session, "binary": binary, "home": str(codex_home())}


def _env(prefixes: tuple[str, ...], suffix: str) -> str:
    for prefix in prefixes:
        value = (os.environ.get(f"{prefix}_{suffix}") or "").strip()
        if value:
            return value
    return ""


def _env_owns(provider: Provider, env_base: str, *, implicit_selection: bool = True) -> bool:
    """Does the role env belong to THIS provider? (i.e. may it claim the key/model in it?)

    The ``EEZE_<ROLE>_*`` variables are not provider-scoped — ``EEZE_PLANNER_API_KEY`` is whoever
    wrote it. Seen live on the Settings card: OpenAI, Google, xAI, Groq and Anthropic ALL reported
    "key from the environment" because they all read OpenRouter's key aloud. Rules:

    * an env endpoint that matches a catalog provider belongs to THAT provider only;
    * an env endpoint nobody recognizes is a custom/self-hosted endpoint — only the implicit
      default provider may claim it (an explicitly selected provider needs its own key);
    * with no env endpoint at all, the role env belongs to the shipped default (OpenRouter).
    A stored endpoint override may claim the env key only if both endpoints are identical.
    """

    if not env_base:
        return provider.id == DEFAULT_PROVIDER_ID
    normalized = env_base.rstrip("/").lower()
    known = {p.base_url.rstrip("/").lower() for p in CATALOG if p.base_url}
    if normalized not in known:
        return implicit_selection
    return normalized == provider.base_url.rstrip("/").lower()


def brain_for(provider: Provider) -> str:
    """Which loop brain a provider implies: the local subscription runs ``codex``, everything else
    the OpenAI-compatible ``llm`` brain."""
    return "codex" if provider.kind == "oauth_external" else "llm"


def default_provider_brain(home: Path | None = None) -> str:
    """The brain the app's chosen provider implies (``llm`` for an API provider, ``codex`` for the
    local subscription), or ``""`` when the user never picked one. This is what makes "Use this
    one" on the Settings screen real instead of a badge that lies."""
    store = SecretStore(home)
    chosen = (store.get("provider.default") or "").strip()
    if not chosen:
        return ""
    try:
        return brain_for(get_provider(chosen))
    except ValueError:
        return ""


def _stored_models(store: SecretStore, provider_id: str) -> dict[str, str]:
    import json

    raw = store.get(f"provider.{provider_id}.models")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v.strip()}


def resolve_provider(
    role: str,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    agent_provider: str | None = None,
    home: Path | None = None,
) -> ProviderConfig:
    """Resolve the effective provider config for a role: run -> agent -> store -> env -> default."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r} — valid: {', '.join(ROLES)}")
    store = SecretStore(home)
    prefixes = ENV_PREFIXES[role]

    selection: str = ""
    source = "default"
    for candidate, layer in (
        (provider_id, "run"),
        (agent_provider, "agent"),
        (store.get("provider.default"), "store"),
        (os.environ.get("EEZE_PROVIDER"), "env"),
    ):
        if candidate and str(candidate).strip():
            selection, source = str(candidate).strip(), layer
            break
    provider = get_provider(selection or DEFAULT_PROVIDER_ID)

    stored_base = (store.get(f"provider.{provider.id}.base_url") or "").strip()
    stored_key = store.get(f"provider.{provider.id}") or ""
    stored_models = _stored_models(store, provider.id)
    tier = "hard" if role in ("planner", "spec") else "routine"

    # The generic EEZE_<ROLE>_* variables belong to the HTTP API providers only. A live probe
    # proved why: EEZE_PLANNER_MODEL=openai/gpt-6-sol (an OpenRouter namespace) leaked into the
    # Codex CLI, which rejects the prefix — and EEZE_PLANNER_BASE_URL leaked into every row.
    # So: api_key providers read the role env; the CLI provider reads EEZE_CODEX_*; local
    # servers read neither (the store override is their documented path). WHICH api_key provider
    # may claim the role env is decided by ``_env_owns`` — see the Settings-card bug there.
    env_base = env_key = env_model = ""
    if provider.kind == "api_key":
        role_base = _env(prefixes, "BASE_URL")
        if _env_owns(provider, role_base, implicit_selection=source == "default"):
            env_base = role_base
            # A stored endpoint override must not inherit a credential bound to another URL.
            if not stored_base or (role_base and stored_base.rstrip("/").lower() == role_base.rstrip("/").lower()):
                env_key = _env(prefixes, "API_KEY")
            env_model = _env(prefixes, "MODEL")
    elif provider.kind == "oauth_external":
        env_model = (os.environ.get("EEZE_CODEX_MODEL") or "").strip() or (
            os.environ.get(f"EEZE_CODEX_MODEL_{tier.upper()}") or ""
        ).strip()

    base_url = stored_base or env_base or provider.base_url
    base_source = "store" if stored_base else "env" if env_base else "default"

    if stored_key and not stored_key_allowed(
            provider, store.get(f"provider.{provider.id}.key_host"), base_url):
        stored_key = ""  # bound to another host: re-enter the key for the new endpoint
    api_key = stored_key or env_key
    key_source = "store" if stored_key else "env" if env_key else "none"

    explicit_model = (model or "").strip()
    stored_model = stored_models.get(tier, "")
    model_value = (
        explicit_model
        or stored_model
        or env_model
        or provider.default_models.get(tier, "")
    )
    model_source = (
        "run"
        if explicit_model
        else "store"
        if stored_model
        else "env"
        if env_model
        else "default"
        if provider.default_models.get(tier)
        else "none"
    )

    return ProviderConfig(
        provider_id=provider.id,
        base_url=base_url,
        api_key=api_key,
        model=model_value,
        source=source,
        brain="codex" if provider.kind == "oauth_external" else "llm",
        sources={"base_url": base_source, "api_key": key_source, "model": model_source},
        note=provider.note,
    )


_MODEL_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/-@+")


def valid_model_id(model: str | None) -> bool:
    """Model ids are plain tokens. Anything else never reaches an argv or a URL.

    The Codex brain runs through ``cmd /c`` on Windows, where ``&``/``|``/``^`` in an
    unquoted argument start a new command — a model named ``x&calc.exe`` ran calc.
    """
    text = str(model or "")
    return 0 < len(text) <= 120 and text[0].isalnum() and all(ch in _MODEL_ID_CHARS for ch in text)


def url_host(url: str | None) -> str:
    """Lower-case host of ``url`` ("" when absent/unparseable)."""
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""


def is_loopback_host(host: str) -> bool:
    if host in {"localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def stored_key_allowed(provider: object, stored_key_host: str | None, base_url: str) -> bool:
    """May a key saved in the local store be sent to ``base_url``?

    A stored key is bound to the host it was saved for. Changing a provider's endpoint must
    never forward the saved key to the new host (that turned "write-only" keys readable: point
    ``base_url`` at your own server, press Test). Keys saved before binding existed are bound
    to the provider's catalog host.
    """
    target = url_host(base_url)
    bound = (stored_key_host or "").lower() or url_host(getattr(provider, "base_url", ""))
    return bool(target) and target == bound


def require_key_for_endpoint_override(base_url: str | None, api_key: str | None, cfg: object) -> None:
    """Do not carry a resolved provider's credential to a different run endpoint."""
    configured_url = str(getattr(cfg, "base_url", "") or "")
    if (base_url and configured_url and not api_key
            and base_url.rstrip("/").lower() != configured_url.rstrip("/").lower()):
        raise ValueError("an endpoint override requires an explicit api_key")


def tier_models(provider_id: str, home: Path | None = None) -> dict[str, str]:
    """The effective routine/hard models for a provider (store override wins). For P3's mapping."""
    provider = get_provider(provider_id)
    stored = _stored_models(SecretStore(home), provider.id)
    return {tier: stored.get(tier) or provider.default_models.get(tier, "") for tier in TIERS}


def provider_status(home: Path | None = None) -> list[dict[str, Any]]:
    """One honest row per provider for ``GET /api/providers`` — never a key value."""
    store = SecretStore(home)
    resolved = resolve_provider("brain", home=home)
    live_brain = (os.environ.get("EEZE_BRAIN") or "").strip().lower() or default_provider_brain(home)
    codex = codex_status()
    rows: list[dict[str, Any]] = []
    for provider in CATALOG:
        cfg = resolve_provider(
            "brain", provider_id=provider.id, home=home
        )  # role=brain: the loop's own view
        stored_key = bool(store.get(f"provider.{provider.id}"))
        if provider.kind == "api_key":
            configured: bool | None = bool(cfg.api_key)
            detail = (
                "key stored locally"
                if stored_key
                else "key from the environment (.env)"
                if cfg.api_key
                else "no key yet — add one to use this provider"
            )
        elif provider.kind == "oauth_external":
            configured = bool(codex["cli"] and codex["session"])
            detail = (
                f"cli found · session present ({codex['home']})"
                if configured
                else "cli missing or no login — run `codex login`"
            )
        else:  # local server: reachability is only known after a live probe
            configured = None
            detail = "no key needed — run Test connection"
        role = ""
        if provider.id == resolved.provider_id:
            role = "model"  # the provider the model layer resolves to
        elif provider.kind == "oauth_external" and live_brain == cfg.brain:
            role = "engine"  # the brain actually running (e.g. the local subscription)
        rows.append(
            {
                "id": provider.id,
                "label": provider.label,
                "kind": provider.kind,
                "compatible": provider.compatible,
                "local_only": provider.local_only,
                "docs_url": provider.docs_url,
                "note": provider.note,
                "brain": cfg.brain,
                "role": role,
                "base_url": cfg.base_url,
                "base_url_source": cfg.sources["base_url"],
                "configured": configured,
                "configured_detail": detail,
                "key_source": cfg.sources["api_key"],
                "key_last4": store.last4(f"provider.{provider.id}"),  # store only; "" when too short
                "key_in_store": stored_key,
                "models": tier_models(provider.id, home=home),
                "is_default": provider.id == resolved.provider_id,
            }
        )
    return rows


def _sanitize(text: object, secret: str, limit: int = 200) -> str:
    """One-line detail with the key REMOVED if a provider echoed it back."""
    out = str(text or "").strip().replace("\n", " ")
    if secret and secret in out:
        out = out.replace(secret, "[key]")
    return out[:limit]


def probe_provider(
    provider_id: str,
    config: ProviderConfig,
    *,
    http_post: Callable[..., Any] | None = None,
    codex_runner: Callable[[list[str], str], tuple[int, str]] | None = None,
    timeout: float = 60.0,
    scratch: Path | None = None,
    binary: str | None = None,
) -> dict[str, Any]:
    """LIVE connection test. Real call to the provider (or the local CLI); never a fake pass."""
    provider = get_provider(provider_id)
    result: dict[str, Any] = {
        "ok": False,
        "provider_id": provider.id,
        "method": "chat_completions",
        "status_code": None,
        "latency_ms": None,
        "model_echo": config.model or "",
        "tokens": None,
        "detail": "",
    }
    if config.provider_id != provider.id:
        result["detail"] = "provider/config mismatch — connection refused"
        return result
    if not provider.compatible:
        result["detail"] = (
            "refused: this provider does not speak the OpenAI chat-completions API "
            "(the llm brain's transport) — tracked in docs/PROVIDERS-PLAN.md"
        )
        return result

    if provider.kind == "oauth_external":
        from eeze_agent.brains.codex import SCRATCH_DEFAULT, codex_exec_once, codex_model_for_tier

        model = config.model or codex_model_for_tier("routine")
        result["method"] = "codex_exec"
        result["model_echo"] = model
        scratch_path = Path(scratch or os.environ.get("EEZE_CODEX_SCRATCH") or SCRATCH_DEFAULT)
        t0 = time.perf_counter()
        try:
            text, tokens = codex_exec_once(
                "You are a connectivity probe for Eeze.",
                "Reply with exactly: OK",
                binary=binary or os.environ.get("EEZE_CODEX_BIN") or "codex",
                model=model,
                scratch=scratch_path,
                timeout=timeout,
                runner=codex_runner,
            )
        except Exception as exc:  # noqa: BLE001 — a failed probe is a report, not a crash
            result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            result["detail"] = f"{type(exc).__name__}: {_sanitize(exc, config.api_key)}"
            return result
        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["tokens"] = tokens
        result["ok"] = "OK" in text.upper()
        result["detail"] = f"subscription answered {_sanitize(text, config.api_key, 60)!r}"
        return result

    if not config.model:
        result["detail"] = (
            "no model set for this provider — set one first "
            f"(PUT /api/providers/{provider.id} with default_models)"
        )
        return result
    if provider.kind == "api_key" and not config.api_key:
        result["detail"] = "no key stored for this provider — add one first"
        return result

    post = http_post or httpx.post
    payload = {
        "model": config.model,
        "temperature": 0,
        "max_tokens": 16,
        "messages": [
            {"role": "system", "content": "You are a connectivity probe for Eeze."},
            {"role": "user", "content": "Reply with exactly: OK"},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    t0 = time.perf_counter()
    try:
        response = post(f"{config.base_url}/chat/completions", json=payload, headers=headers, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — transport failures are honest report lines
        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["detail"] = f"transport error: {type(exc).__name__}: {_sanitize(exc, config.api_key)}"
        return result
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    result["status_code"] = getattr(response, "status_code", None)
    if result["status_code"] == 200:
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"] or ""
        except Exception:  # noqa: BLE001 — a 200 with a body we cannot parse is not a pass
            result["detail"] = "answered 200 but the body had no choices[] — not counted as a pass"
            return result
        usage = (body.get("usage") or {}) if isinstance(body, dict) else {}
        result["tokens"] = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        result["model_echo"] = str(body.get("model") or config.model)
        result["ok"] = "OK" in str(text).upper()
        result["detail"] = f"answered {_sanitize(text, config.api_key, 60)!r}"
        return result
    try:
        body_text = response.text
    except Exception:  # noqa: BLE001
        body_text = ""
    result["detail"] = f"HTTP {result['status_code']}: {_sanitize(body_text, config.api_key)}"
    return result
