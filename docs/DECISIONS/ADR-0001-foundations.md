# ADR-0001 — Project foundations

Date: 2026-09-18 · Status: accepted

## Context

Kickoff for Eeze Agent: a vertical computer-use agent combining Jev (TypeSafe System One)
as the tactical brain and cua-driver (trycua/cua) as the background automation hands,
with our own orchestrator as the product spine. Decisions below were locked during the
kickoff review.

## Decisions

1. **Name:** Eeze Agent. Repo `eeze-agent`, package `eeze_agent`, CLI `eeze`.
2. **English-first:** all code, docs, prompts, and UI copy in English.
3. **Orchestrator stack:** Python (uv, pydantic v2, FastAPI, SQLite). Web control plane
   later. Rationale: typesafe-sdk and cua Python SDK are Python; consistent with existing
   FastAPI+SQLite experience on this machine; driver is language-neutral (CLI/MCP).
4. **First OS target:** Windows (dev machine, testable today); macOS next.
5. **Jev access:** direct API key, wired via `TYPESAFE_API_KEY` (never in git; `.env`).
6. **First vertical:** deferred until a pilot user is in hand (after the walking skeleton).
7. **Loop ownership:** code owns observe→decide→act→verify; Jev answers batched typed
   judgments; a System 2 LLM only plans and replans.

## Consequences

- The vendor surface stays thin: Jev, planner, and driver are each behind a port.
- No code depends on the driver's MCP vocabulary directly; the DriverPort normalizes it.
- Vertical workflow work (F4+) can start without re-architecting the core.
