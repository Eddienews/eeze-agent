# ADR-0002 — Multi-agent support from day one

Date: 2026-09-18 · Status: accepted

## Context

Product vision: the user creates multiple named agents (e.g. **Fin** for finance,
**Inbox** for email, **Scout** for research). Each agent has its own role,
permissions and tools, isolated memory, its own routines, and a separate lane in
the approvals inbox. F1 ships no multi-agent UI — but the architecture must make
multi-agent **additive**, never a later refactor of core tables and signatures.

## Decision

1. **`Agent` model**: `id`, `name`, `role`, `permissions`, `tools` (plus the
   registry below). F1 registers a single `default` agent — built-in fallback and
   an optional `agents.yaml` at the repo root.
2. **`AgentContext`** (`agents/models.py`) is created at run-set start and passed
   **as a parameter** to the three ports — Brain (select/verify), Driver (every
   observe/act operation), Planner (from F2) — and threaded through the loop.
3. **`agent_id` everywhere**: every journal record (runs, steps, judgments,
   actions) is stamped now; the SQLite schema (F3) will carry an `agent_id`
   column on every relevant table — `runs`, `steps`, `memory`, `routines`,
   `approvals` — denormalized onto child tables so any query can filter by agent
   without a join.
4. **Permissions shape** (enforced by the loop; trivial for the F1 `default`):
   `risk_classes` (read / write_local / send / pay), `apps` allowlist,
   `allow_foreground`; `tools` lists the permitted tool names.
5. **Approvals are addressed to an agent** (`approvals.agent_id`) so each agent
   gets its own inbox lane.

## Consequences

- Ports gain one parameter now instead of a signature churn later.
- Memory/routines/approvals isolation is structural from the first persistence
  layer; per-agent filtering is a WHERE clause, not a migration.
- F1 scope is unchanged: still the walking skeleton on Notepad with one
  `default` agent; the multi-agent UI/API arrives with the control plane (F5).
