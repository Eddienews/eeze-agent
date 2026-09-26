"""Per-model USD pricing for the metrics report (measured 2026-09-23).

Blended per-million-token numbers come from LIVE single-judgment calls (see
``docs/ROUTER.md``): one Eeze judgment sends ~1.07k input tokens and receives
~20-40 output tokens, so the blend sits within ~2% of the input price. These are
estimates for reporting — never billing truth, and never a reason to change a model.
"""

from __future__ import annotations

MODEL_PRICES_USD_PER_MTOK: dict[str, float] = {
    # TypeSafe Jev — input-billed, measured across 502 calls (avg $0.000107/call)
    "jev-1.13.0": 0.042,
    # $0.10/$0.50 per M — live blend: 1069 in / 25 out -> $0.000119 for 1094 tokens
    "openai/gpt-6-luna": 0.11,
    # $2/$10 per M — live blend: 1069 in / 16 out -> $0.002298 for 1085 tokens
    "openai/gpt-6-sol": 2.12,
    # retired tier (2026-09-23) — kept so old journals still price correctly
    "deepseek/deepseek-chat": 0.34,
}

DEFAULT_PRICE_USD_PER_MTOK = 0.042  # jev, the historical default (journals with no model)

# A model this table does not know is priced conservatively high, not at Jev's rate: pricing
# every OpenAI/Google/xAI/Groq model as Jev under-reported spend by ~50x, and a budget check
# built on that would never trip. Add real rows above as models get measured.
UNKNOWN_MODEL_PRICE_USD_PER_MTOK = 3.0

# The Codex-subscription brain bills nothing per token — a flat plan. That makes a run's
# MARGINAL cost a true $0.00 (the plan's own cost is out of band), not a missing number.
FLAT_PLAN_PREFIXES = ("codex:",)


def price_for(model: str | None) -> float:
    """Blended USD per million tokens for ``model`` (default price when unknown)."""
    name = str(model or "")
    if name.startswith(FLAT_PLAN_PREFIXES):
        return 0.0
    if not name or name.startswith("jev"):
        return MODEL_PRICES_USD_PER_MTOK.get(name, DEFAULT_PRICE_USD_PER_MTOK)
    return MODEL_PRICES_USD_PER_MTOK.get(name, UNKNOWN_MODEL_PRICE_USD_PER_MTOK)


def estimate_cost_usd(model: str | None, tokens: int) -> float:
    """Estimated USD cost of ``tokens`` spent on ``model`` (rounded to 7 places)."""
    return round(max(0, int(tokens or 0)) / 1e6 * price_for(model), 7)
