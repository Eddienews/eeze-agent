# Eeze Agent — Architecture

Status: draft v0.2 (F1) · Last updated: 2026-09-18

Eeze Agent is a **vertical computer-use agent**: a persistent digital coworker that
operates any software on the user's machine — browser, terminal, native apps — in the
background, without stealing cursor or focus.

## Thesis

We buy the brain and the hands; we build the spine and the product.

| Layer | Component | Why |
| --- | --- | --- |
| Tactical brain | **Jev** (TypeSafe System One) | Fast typed judgments: ~100 ms, calibrated probabilities, ~$0.042/MTok input, output free. No string generation — answers slot into code as typed values. |
| Hands | **cua-driver** (trycua/cua, MIT) | Background desktop automation on macOS/Windows/Linux. Structured verdicts per action; escalation ladder background → pixel → foreground. |
| Spine | **this repo** | Observe→decide→act→verify loop, task state, memory, safety, routines, scheduler, local control plane. |

The differentiation is not "computer use" (a commodity); it is **orchestration +
verticalization + UX**: packaged, reliable workflows for a niche, installable by
non-technical users.

## Verified environment (F0, on the dev machine)

- cua-driver **0.28.1**, installed at `%LOCALAPPDATA%\Programs\Cua\cua-driver` —
  live smoke: `cua-driver call list_apps` returns real running apps.
- **typesafe-sdk 0.6.0** (Python) installed and field-verified. Known quirks: Score is a
  0-indexed float; Noul answers have no separate confidence field; batching independent
  questions in one call is ~11.5x cheaper / ~9.6x faster than one call per question.
- Toolchain: Python 3.11.16, uv 0.12.13, git 2.38.
- F0 spike results (see `docs/SPIKES.md`): loop cycle p50 ≈ 4.0 s (Jev ≈ 165 ms of it),
  10/10 success on the Notepad task, ~$0.00007/cycle, zero focus steals observed.
- F1 (walking skeleton) — full detail in `docs/F1-REPORT.md`: cua-driver **0.28.2**;
  the F1 task (Notepad: set content → File ▸ Save as → write path → save → verify on
  disk) runs end-to-end via `eeze run`. Write ladder (`set_value` → word-select +
  `type_text` → …), deterministic window selection (on-screen / not-minimized /
  largest area) and recovery (minimized window → `bring_to_front`) live in code.

## Architecture

```text
┌────────────────────────────────────────────────────────────────┐
│ Control plane (local)           FastAPI · SQLite · dashboard   │
└──────────────┬─────────────────────────────────────────────────┘
               │ goals · approvals · runs · routines · audit
┌──────────────▼─────────────────────────────────────────────────┐
│ ORCHESTRATOR — loop · escalation · scheduler · memory · safety │
└──────┬───────────────────┬───────────────────┬─────────────────┘
       │ PlannerPort       │ BrainPort         │ DriverPort
       ▼                   ▼                   ▼
  System 2 LLM            Jev               cua-driver
  (plan / re-plan)     (judgments)      (observe / act)
```

### Ports and adapters

- **BrainPort** — judgment interface backed by Jev; the vendor is one adapter, swappable.
- **PlannerPort** — System 2 planning/replanning; any LLM with structured output
  (OpenRouter first). Consulted at task start and on replan only.
- **DriverPort** — observe/act interface backed by cua-driver (CLI now; MCP / in-process
  `cua_driver` SDK evaluated in F1).
- **Memory** — local SQLite + artifacts; provider-independent.

### The loop (one cycle)

1. **Observe** — `driver.capture(app=…)` → normalized `Observation`: AX tree (primary
   state), screenshot (artifact), window meta.
2. **Decide** — ONE batched Jev request per cycle over a filtered state:
   - `select_element` (Choice over code-built candidates + `none_match`)
   - `step_done` (Noul)
   - `blocker` (Choice: none | dialog | login | captcha | error)
   - `escalate` (Noul) — optional, confidence-gated
3. **Act** — translate the chosen answer into one driver action. Honor the driver's
   verdict (`confirmed` | `unverifiable` | `suspected_noop`) and escalate only on a
   returned signal: background → pixel → foreground (consented) → human.
4. **Verify** — read-back via driver, else fresh capture + `step_done`.
5. **Continue / escalate / replan** — no-progress policy: ×N retries → vision LLM on the
   screenshot → planner re-plan → ask the user.

### Design rules (from Jev's documented jagged edges)

- Filter state before sending it — unrelated detail costs accuracy (context rot).
- Keep arithmetic, counting, and dates in code; Jev extracts and judges, code computes.
- One hop per judgment; instructions worded exactly; criteria mirror the instructions.
- Treat screen content as hostile input (prompt injection): the user's prompt is the only
  source of truth; page/dialog text is data, never instructions.
- Don't assume structural invariance between question forms; tune thresholds per question
  on real data; pin the model version and log it on every response.

### Capability ladder

1. APIs / CLI / files / shell — prefer any deterministic path that exists.
2. GUI with AX tree + background input — the Jev-driven core.
3. GUI pixels (coordinate) — when AX is degraded; vision LLM assists.
4. Foreground input — consented, when background routes verifiably fail.
5. Human — for risk and ambiguity.

### Memory

- SQLite (WAL) with an append-only action journal (audit-grade); artifacts on disk with
  retention and redaction; recall (FTS5 / embeddings) added when needed.
- Local-first: only state text → Jev and goal text → planner leave the machine; both
  redactable.

### Safety

- Risk classes: read / write-local / send / pay → approval inbox for the risky ones.
- Never types secrets; app allowlists; driver runs in its `bounded` permission mode.
- Kill switch; full audit journal; `eeze doctor` self-check.

## Coexistence with Human and System Activity

The machine is shared: the user types, apps auto-save, services inject input, and
background agents (not just ours) may act. The loop treats **external input noise** as
a first-class failure class, not an edge case (incident: the "v-storm", 2026-09-18 —
`docs/SPIKES.md`).

**Definition.** External input noise = any state change we did not cause: a mutated
field, an unexpected window, a document that grows while the agent is idle on it.

**Response (implemented, `core/loop.py`).**

- **Detect**: every text-action readback is classified
  (`ok | noop | append | foreign_mutation | unexpected_change`); `state_sig`
  fingerprints surround non-text actions. A mutation that is neither the previous
  value, nor the target text, nor our own append is external. (Rate-based anomaly
  scoring over state deltas — sustained churn rather than a single readback — is the
  F2/F3 generalization of this same class.)
- **Pause + log**: the run stops immediately and the journal records
  `external_input_detected` (before / after / expected / element). The run is excluded
  from the success metric and reported separately; three consecutive hits abort the
  run-set — *prefer 15 clean runs to 20 polluted ones*.
- **Never auto-correct**: we do not fight, "fix", or blindly retry over foreign input.
  The agent pauses and the event is surfaced (approvals/notification lane, F2+).

**Scope note.** Detection is per-action for text mutations (the incident class);
click-level attribution is deliberately deferred — clicks record `state_sig` deltas as
evidence only.

## Locked decisions

See `docs/DECISIONS/ADR-0001-foundations.md` — English-first, Python orchestrator,
Windows-first, Jev direct API key, vertical chosen later with a pilot user.

## What we are not building

Our own driver, our own model, our own browser engine. No Eeze MCP server in v1.
