# Eeze Agent — HTTP API (draft v0.1)

Status: **read-only slice implemented (F1.5)**. Live today: `GET /agents`,
`GET /agents/{id}`, `GET /approvals` (empty page — final shape), `GET /runs`,
`GET /runs/{id}`, `GET /system/status`. Serve with `uv run eeze api` (openapi at
`/docs`, run artifacts mounted at `/artifacts`). The rest of this document is the
contract the desktop frontend wires against; it follows the domain models in
`src/eeze_agent` (agents, runs, approvals) and the ADRs in `docs/DECISIONS/`.

- Base URL (local): `http://127.0.0.1:8765` — served by the **detached daemon**
  (`uv run eeze api start|stop|status`; pid `~/.eeze/api.pid`, log `~/.eeze/api.log`,
  binds `0.0.0.0` + `--port 8765`). Foreground serve still available: `uv run eeze api`.
- Canonical prefix: **`/api/*`** (the UI and the Vite dev proxy use it) — the ONLY
  prefix. The root belongs to the SPA (client routes like `/approvals` are never
  shadowed by API aliases). In production the backend also serves the built UI
  (`ui/dist`) at `/` with SPA fallback.
- Public dev URL: `uv run eeze tunnel start` starts a cloudflared quick tunnel and prints
  a `https://<name>.trycloudflare.com` URL (`eeze tunnel url|stop` to manage).
- CORS (dev): origins `http://localhost:5173`, `http://localhost:3000`, any
  `https://*.lovable.(app|dev|project.com)` and any `https://*.trycloudflare.com` are
  allowed — `access-control-allow-origin` echoes the requesting origin, credentials on.
- Auth: none by default (local dev / tunnel). When exposing beyond your own machine,
  every request requires `Authorization: Bearer $EEZE_API_TOKEN` (F5 installer sets it).
- Content type: JSON everywhere (`application/json`), timestamps ISO-8601 UTC,
  ids are strings (`agent_id`, `run_id`, `step_id`, `approval_id`).
- Money: USD floats, 6 decimals. Latency: milliseconds (floats).
- Pagination: `?limit=&offset=` on all list endpoints (default `limit=50`, max `200`).
  Responses use the `Page` envelope.
- Errors: canonical envelope `{"error": {"code": "...", "message": "...", "detail": {}}}`.
  Codes: `not_found`, `invalid_input`, `conflict`, `rate_limited`, `internal`.
- Long operations return `202 Accepted` with the created resource id.

## Endpoints overview

| Method | Path | Purpose | Phase when backed by real data |
| --- | --- | --- | --- |
| GET | `/agents` | list agents + status/metrics | ✅ implemented (F1.5); SQLite-backed in F3 |
| GET | `/agents/{id}` | agent detail | ✅ implemented (F1.5); F3 persisted |
| POST | `/agents` | create agent (wizard payload) | F3 (persisted in SQLite) |
| PATCH | `/agents/{id}` | update settings | F3 |
| POST | `/agents/{id}/pause` | pause/resume toggle | F2.5 (cooperative pause) |
| GET | `/approvals` | pending approvals (filters) | ✅ stub (empty page, final shape); store in F2 |
| POST | `/approvals/{id}/approve` | approve | F2 |
| POST | `/approvals/{id}/reject` | reject (reason required) | F2 |
| POST | `/approvals/{id}/ask-why` | explanation from the agent | F2 |
| GET | `/runs` | list runs (filters) | ✅ implemented (F1.5, journal-backed) |
| GET | `/runs/{id}` | run detail: steps, decisions, artifacts | ✅ implemented (F1.5) |
| POST | `/runs/{id}/replay` | re-execute the same task spec | F3 |
| GET | `/runs/{id}/export` | audit export (jsonl/markdown) | F3 |
| POST | `/tasks` | submit a task (command bar) | F1.5 for `task_name`; F2 for `goal` |
| GET | `/system/status` | daemon/driver/Jev health | ✅ implemented (F1.5) |
| POST | `/system/kill-switch` | emergency stop all agents | F2 (executor supports cancel) |
| GET | `/events` (SSE) | live run/approval events | F3 |

"F1.5" = a read-only slice we can ship immediately after F1 if the frontend wants to
start wiring against real data (all of it exists in `artifacts/runs/*/journal.jsonl`
plus the agent registry).

## Schemas (Pydantic v2 style)

```python
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)

class ErrorEnvelope(BaseModel):
    error: ErrorBody

# ---------- agents ----------

class AgentPermissions(BaseModel):
    risk_classes: list[Literal["read", "write_local", "send", "pay"]]
    apps: list[str] = ["*"]          # allowlist ("*" = any)
    allow_foreground: bool = False

class AgentModelConfig(BaseModel):
    brain: str = "jev-1.13.0"        # tactical judgments
    planner: str | None = None        # System 2 model id (F2)

class AgentMetrics(BaseModel):
    runs_24h: int = 0
    success_rate_7d: float | None = None
    avg_cycle_ms: float | None = None
    cost_30d_usd: float = 0.0

class Agent(BaseModel):
    id: str                           # slug: "fin", "inbox", "scout"
    name: str
    role: str = "generalist"
    description: str | None = None
    permissions: AgentPermissions
    tools: list[str] = ["*"]
    model: AgentModelConfig = AgentModelConfig()
    budget_usd_daily: float | None = None
    paused: bool = False
    status: Literal["idle", "running", "paused", "attention"] = "idle"
    current_run_id: str | None = None
    metrics: AgentMetrics = AgentMetrics()
    created_at: datetime

class AgentCreate(BaseModel):        # Create Agent Wizard payload
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    name: str
    role: str = "generalist"
    description: str | None = None
    permissions: AgentPermissions
    tools: list[str] = ["*"]
    model: AgentModelConfig = AgentModelConfig()
    budget_usd_daily: float | None = None

class AgentUpdate(BaseModel):        # PATCH semantics: only provided fields change
    name: str | None = None
    description: str | None = None
    permissions: AgentPermissions | None = None
    tools: list[str] | None = None
    model: AgentModelConfig | None = None
    budget_usd_daily: float | None = None

class PauseState(BaseModel):
    agent_id: str
    paused: bool
    changed_at: datetime

# ---------- approvals ----------

class Approval(BaseModel):
    id: str
    agent_id: str
    run_id: str
    step_id: str
    title: str                        # human summary of the pending action
    risk_class: Literal["send", "pay", "write_local"]
    payload_preview: dict[str, Any]   # e.g. the message about to be sent
    rationale: str | None = None      # why the agent wants this
    requested_at: datetime
    expires_at: datetime | None = None
    status: Literal["pending", "approved", "rejected", "expired"]

class ApprovalDecision(BaseModel):
    note: str | None = None

class RejectionDecision(BaseModel):
    reason: str = Field(min_length=3)

class AskWhyResponse(BaseModel):
    explanation: str
    model: str
    generated_at: datetime
    latency_ms: float

# ---------- runs ----------

class RunStepJudgment(BaseModel):
    kind: Literal["select_element", "verify"]
    question: str
    answer: str | None = None
    confidence: float | None = None
    noul: float | None = None
    ms: float
    tokens: int = 0

class RunStep(BaseModel):
    id: str
    index: int
    action: Literal["set_text", "click", "invoke_menu", "hotkey", "check", "run_script"]
    intent: str
    selected: str | None = None      # e.g. "Edit 'File name:'"
    write_method: str | None = None  # ladder rung that worked
    verification: str | None = None  # serialized verify reasons
    ok: bool
    attempts: int = 1
    interference: bool = False
    judgment: RunStepJudgment | None = None
    ms: float
    artifacts: list[str] = []        # e.g. ["screenshots/step-set_filename.png"]

class Run(BaseModel):
    id: str                          # "{runset_id}.{run_index}"
    runset_id: str
    agent_id: str
    task_name: str
    status: Literal["running", "ok", "failed", "interference", "aborted"]
    started_at: datetime
    ended_at: datetime | None = None
    cycle_ms: float | None = None
    cost_usd: float | None = None
    interference: bool = False
    error: str | None = None

class RunDetail(Run):
    steps: list[RunStep]
    journal_url: str                 # /artifacts/runs/{runset}/journal.jsonl
    summary: dict[str, Any] | None = None

class RunSummaryPage(Page[Run]):     # GET /runs response
    pass

# ---------- tasks ----------

class TaskSubmit(BaseModel):
    agent_id: str
    task_name: str | None = None     # a registered task spec (works today)
    task_yaml: str | None = None     # inline spec (F3)
    goal: str | None = None          # NL goal → planner (F2)
    params: dict[str, str] = {}      # template variables
    priority: Literal["low", "normal", "high"] = "normal"

class TaskAccepted(BaseModel):
    run_id: str
    agent_id: str
    status: Literal["queued", "running"]

# ---------- system ----------

class DaemonStatus(BaseModel):
    running: bool
    pid: int | None = None
    version: str | None = None
    permission_mode: str | None = None   # e.g. "standard"

class JevStatus(BaseModel):
    calls_24h: int = 0
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    cost_24h_usd: float = 0.0
    model: str = "jev-1.13.0"

class SystemStatus(BaseModel):
    daemon: DaemonStatus
    jev: JevStatus
    agents: list[Agent] = []
    active_runs: int = 0
    interference_events_24h: int = 0
    kill_switch_engaged: bool = False
    uptime_s: float | None = None

class KillSwitchState(BaseModel):
    engaged: bool
    stopped_run_ids: list[str] = []
    changed_at: datetime
```

## Endpoint details

### Agents

- `GET /agents` → `Page[Agent]`. Query: `status?` (`idle|running|paused|attention`).
- `GET /agents/{id}` → `Agent` (404 `not_found`).
- `POST /agents` → `201 Agent`, body `AgentCreate`. `409 conflict` on duplicate id.
  The registry persists new agents once F3 lands; today only the built-in `default`
  exists (`agents.yaml`).
- `PATCH /agents/{id}` → `Agent`, body `AgentUpdate` (partial).
- `POST /agents/{id}/pause` → `PauseState`. Body `{"paused": bool}` (toggle target
  state, idempotent). Cooperative: a currently running step finishes; the run pauses
  before its next step.

### Approvals

- `GET /approvals` → `Page[Approval]`. Query: `agent_id?`, `status?` (default
  `pending`), `risk?` (`send|pay|write_local`).
- `POST /approvals/{id}/approve` → `Approval` with `status="approved"`.
  Body `ApprovalDecision` (optional note).
- `POST /approvals/{id}/reject` → `Approval` with `status="rejected"`.
  Body `RejectionDecision` (**reason required** — it is recorded in the audit journal
  and given back to the agent as feedback).
- `POST /approvals/{id}/ask-why` → `AskWhyResponse` (200). Generates an explanation
  from the run journal context with the agent's planner model. Synchronous; expect
  2–5 s. `429` if requested more than once per 30 s per approval.

### Runs

- `GET /runs` → `Page[Run]`. Query: `agent_id?`, `status?`, `task_name?`,
  `from?`/`to?` (ISO dates), `interference?` (bool).
- `GET /runs/{id}` → `RunDetail` (steps include their Jev judgments and artifacts).
- `POST /runs/{id}/replay` → `202 TaskAccepted` — re-executes the **same task spec
  with the same params** in a new run (never overwrites the original; the original
  journal is immutable — audit requirement).
- `GET /runs/{id}/export` → `text/plain` (markdown) or `application/x-ndjson`
  (`?format=jsonl`), `Content-Disposition: attachment`. Contains: run meta, every
  step, judgments, verifications, refusals, interference events, cost.

### Tasks

- `POST /tasks` → `202 TaskAccepted`.
  - `task_name` (registered spec) works today.
  - `goal` (natural language) requires the F2 planner.
  - Exactly one of `task_name|task_yaml|goal` must be set (`400 invalid_input`).

### System

- `GET /system/status` → `SystemStatus`. Backed by `cua-driver status`, the journal
  aggregates, and the agent registry.
- `POST /system/kill-switch` → `KillSwitchState`. Body `{"confirm": true}` required.
  Sets global pause and cooperatively stops every active run. Idempotent.

### Events (future)

- `GET /events` → Server-Sent Events stream of `run_started|step_finished|
  run_finished|approval_requested|approval_decided|interference_detected`.
  Not needed for the first wiring round.

## Notes for the frontend team

1. The **Team Dashboard** maps to `GET /agents` + `GET /system/status`.
2. The **Approval Inbox** maps to `GET /approvals` (+ approve/reject/ask-why).
3. The **Agent Detail View** maps to `GET /agents/{id}` + `GET /runs?agent_id=`.
4. The **Create Agent Wizard** maps to `POST /agents` (+ `PATCH` on edit).
5. The **Run Viewer** maps to `GET /runs` + `GET /runs/{id}` (steps → timeline).
6. Artifact files (screenshots, journals) are served read-only under
   `GET /artifacts/...` (static). URLs in responses are relative to the base URL.
7. `default` is the only agent in the registry today; treat `agents[]` as the
   source of truth once the API slice ships.

## Write endpoints (F2 — local-only, token-gated)

All writes require the header `X-EEZE-Token: <~/.eeze/api.token>` (the file is created on
the first write attempt) and are **refused when proxy headers** (`CF-Connecting-IP`,
`X-Forwarded-For`) are present — never expose them through a tunnel.

- `GET /approvals?status=pending` — approval queue (risk class, payload preview, run id)
- `POST /approvals/{id}/decide` — body `{decision: approve|deny, grant?: {scope:
  task|agent, ttl_hours?}, auto_resume?: bool (default true), reason?}`. `grant` creates a
  scoped, revocable, TTL-capped permission; `auto_resume` spawns `eeze run --resume <id>`
  detached (log at `~/.eeze/resume-<id>.log`)
- `GET /grants[?include_revoked=true]` — grants with status `active|expired|revoked`
- `DELETE /grants/{id}` — revoke
- `GET /system/status` now carries `pending_approvals`

### Gated runs (CLI)

`eeze run <task.yaml>` pauses with exit code **3** when a step's risk class is outside the
agent policy (`agents.yaml → permissions.risk_classes`; default `read,write_local`) and no
grant covers it: the summary carries `status: needs_approval` + `approval_id`, and the
journal records `approval_requested`. Resume with `eeze run --resume <approval_id>` — only
after the approval is `approved` (a denied approval refuses to resume). Extra classes may be
allowed per run with `--allow install_exec,destructive,...`.

## Providers (P2 — BYO keys, local-only)

Keys are entered on this machine and stored in `~/.eeze/secrets.json` (0600 on POSIX). **No
endpoint ever returns a key value** — rows carry presence (`configured`, `key_in_store`,
`key_source`) and `last4` for stored keys only.

- `GET /providers` → rows: `id, label, kind (api_key|oauth_external|local), compatible,
  local_only, docs_url, note, brain (llm|codex), role (model|engine|""), base_url,
  base_url_source, configured, configured_detail, key_source, key_last4, key_in_store,
  models{routine,hard}, is_default`. `role=model` marks the provider the model layer resolves to;
  `role=engine` marks the brain actually running (the local subscription when `EEZE_BRAIN=codex`).
- `POST /providers/{id}/key` `{key}` → `{ok, id, key_last4, configured}`. 401 without a token,
  409 for the Codex subscription / local servers / an incompatible provider.
- `DELETE /providers/{id}/key` → `{ok, id, removed}`.
- `PUT /providers/{id}` `{base_url?, default_models?, set_default?}` → the updated row.
  `base_url` must be `http(s)://…` (422 otherwise); empty string/object clears an override.
- `POST /providers/{id}/test` → **live probe**. API-kind: one `chat/completions` call, returns
  `{ok, method: "chat_completions", status_code, latency_ms, model_echo, tokens, detail}` with the
  key redacted from any echoed error. Codex: one real CLI judgment (`method: "codex_exec"`,
  `model_echo: gpt-6-luna|gpt-6-sol`). Token-gated because it can spend a paid call.

Resolution precedence for a brain instance (per field): **run override → agent config → user
default (store) → env → built-in default**; `EEZE_PROVIDER` selects the provider by env. The
generic role env applies to `api_key` providers only (the CLI provider reads `EEZE_CODEX_*`).

## Missions (F7 — the composer, local-first)

A mission is one YAML file per mission under `~/.eeze/missions/` (`EEZE_MISSIONS`): `id, name,
kind (3d|video|task), agent_id, goal, plan, sources, schedule`. The plan is the exact text the
runner will read; `plan_meta` reports `{edited, model, tokens, cost_usd, ms}` when it came from a
draft. `last_run` carries `{runset_id, status, approval_id, out_dir, at}`.

- `GET /missions` → `{items, total, limit, offset}` (list rows carry `has_plan`, `plan_chars`,
  `schedule`, `last_run` — not the plan text).
- `GET /missions/{id}` → the mission, **including** `plan`; 404 with a plain message when absent.
- `POST /missions` `{id, name?, kind, agent_id?, goal?, plan?, sources?, schedule?}` → the saved
  mission. Ids are slugs (`torus-turntable`); saving upserts. `schedule` = `{type:
  on_demand|daily|every, at?, minutes?}`; the save syncs exactly one routine `mission:<id>` and
  answers with an honest `note` (`saved — on demand (the previous schedule was removed)`).
- `DELETE /missions/{id}` → `{ok, removed, routine_removed}`.
- `POST /missions/draft` `{kind, goal, name?, sources?}` → `{plan, plan_kind, model, attempts[],
  tokens, cost_usd, ms}`. **A refusal is a 422** in the standard envelope
  (`{"error": {code, message, detail}}`) with the writer's attempts in `detail.attempts` and no
  fallback silently used. A video mission without `sources` is refused before any model call.
- `POST /missions/validate` `{kind?, plan, sources?}` → `{ok, errors[]}` — **stateless**: a draft
  validates before it is ever saved. `POST /missions/{id}/validate` is the same check against the
  stored mission. Validation loads the plan through the real loader, so an invalid YAML (or a spec
  the vertical would reject) is caught here, never at run time.
- `POST /missions/{id}/run` → `{ok, spawned, log}` — detached `eeze mission run <id>`, which is the
  normal gated flow: the first run pauses for approval, later runs of the same mission reuse the
  grant. Token-gated (it starts work).

CLI: `eeze mission list | show <id> | run <id>` (`EEZE_MISSIONS` overrides the store directory).
