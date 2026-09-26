"""API schemas — mirrors docs/API.md (read-only slice, F1.5)."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class AgentPermissions(BaseModel):
    risk_classes: list[str] = Field(default_factory=list)
    apps: list[str] = Field(default_factory=lambda: ["*"])
    allow_foreground: bool = False


class AgentModelConfig(BaseModel):
    brain: str = "jev-1.13.0"
    planner: str | None = None


class AgentMetrics(BaseModel):
    runs_total: int = 0
    runs_24h: int = 0
    success_rate: float | None = None
    avg_cycle_ms: float | None = None
    cost_usd: float = 0.0


class Agent(BaseModel):
    id: str
    name: str
    role: str = "generalist"
    description: str | None = None
    permissions: AgentPermissions
    tools: list[str] = Field(default_factory=lambda: ["*"])
    model: AgentModelConfig = Field(default_factory=AgentModelConfig)
    budget_usd_daily: float | None = None
    budget_effective_usd: float | None = None
    spent_today_usd: float = 0.0
    paused: bool = False
    status: Literal["idle", "running", "paused", "attention"] = "idle"
    current_run_id: str | None = None
    metrics: AgentMetrics = Field(default_factory=AgentMetrics)
    created_at: str | None = None
    source: Literal["repo", "user"] = "repo"


class Approval(BaseModel):
    id: str
    agent_id: str
    run_id: str
    step_id: str = ""
    title: str = ""
    risk_class: str = "write_local"
    payload_preview: dict = Field(default_factory=dict)
    requested_at: str | None = None
    status: str = "pending"
    resumable: bool = False


class GrantRequest(BaseModel):
    """How long an "approve & always allow" should last (F2)."""

    scope: Literal["task", "agent"] = "task"
    # Grants always expire: "forever" is how one old click keeps waving risky steps through.
    ttl_hours: int = Field(default=24, ge=1, le=24 * 30)


class ApprovalDecision(BaseModel):
    # "abandon" closes a pending approval without running anything; it is the only
    # decision allowed on legacy rows that cannot resume.
    decision: Literal["approve", "deny", "abandon"]
    grant: GrantRequest | None = None
    auto_resume: bool = True
    reason: str | None = None


class Grant(BaseModel):
    id: str
    agent_id: str
    risk_class: str
    scope: str
    task: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    status: Literal["active", "expired", "revoked"] = "active"


class RunStepJudgment(BaseModel):
    kind: str
    question: str = ""
    answer: str | None = None
    confidence: float | None = None
    noul: float | None = None
    ms: float | None = None


class RunStep(BaseModel):
    id: str
    index: int = 0
    action: str = ""
    intent: str = ""
    selected: str | None = None
    write_method: str | None = None
    verification: str | None = None
    ok: bool = False
    attempts: int = 1
    interference: bool = False
    judgment: RunStepJudgment | None = None
    ms: float | None = None
    artifacts: list[str] = Field(default_factory=list)


class Run(BaseModel):
    id: str
    runset_id: str
    agent_id: str | None = None
    task_name: str = ""
    status: str = "ok"
    started_at: str | None = None
    ended_at: str | None = None
    cycle_ms: float | None = None
    cost_usd: float | None = None
    interference: bool = False
    error: str | None = None


class RunDetail(Run):
    steps: list[RunStep] = Field(default_factory=list)
    journal_url: str | None = None
    summary: dict | None = None


class DaemonStatus(BaseModel):
    running: bool = False
    pid: int | None = None
    permission_mode: str | None = None


class JevStatus(BaseModel):
    calls: int = 0
    latency_ms_p50: float | None = None
    cost_usd: float = 0.0
    model: str = "jev-1.13.0"


class SystemStatus(BaseModel):
    daemon: DaemonStatus
    jev: JevStatus
    agents: list[Agent] = Field(default_factory=list)
    runs_total: int = 0
    interference_events: int = 0
    pending_approvals: int = 0
    notifications_enabled: bool = True
    routine_failure_notifications_enabled: bool = False


class NotifyToggle(BaseModel):
    enabled: bool


class SystemInfo(BaseModel):
    """Read-only runtime facts for the Settings page. Never carries secret values."""

    version: str = "0.0.1"
    python: str = ""
    api_pid: int = 0
    daemon: DaemonStatus
    store_path: str = ""
    token_path: str = ""
    user_agents_path: str = ""
    repo_agents_path: str = ""
    artifacts_path: str = ""
    keys: dict[str, bool] = Field(default_factory=dict)
    runsets: int = 0
    backups: int = 0


# ---------------- routines + setup (F5) ----------------


class RoutineSchedule(BaseModel):
    type: Literal["daily", "every"]
    at: str | None = None  # daily: "HH:MM"
    minutes: int | None = Field(default=None, ge=1, le=1440)  # every: N minutes


# Risk classes a routine may pre-allow from the HTTP API. Anything that sends, installs,
# destroys or touches the system must keep its gate: one POST must not be able to turn a
# scheduled routine into an unattended mailer. (The CLI can still widen a policy locally.)
API_ROUTINE_ALLOWABLE = frozenset({"read", "write_local"})


class RoutineParams(BaseModel):
    search: str | None = Field(default=None, max_length=500)
    email_summary: bool = False
    email_to: str | None = Field(default=None, max_length=320,
                                 pattern=r"^[^@\s,;<>]{1,64}@[A-Za-z0-9.-]{1,253}$")
    task_path: str | None = None
    runs: int | None = Field(default=None, ge=1, le=50)
    demo: bool = False
    allow: list[str] = Field(default_factory=list)

    @field_validator("search")
    @classmethod
    def _search_is_criteria_only(cls, value: str | None) -> str | None:
        if value is not None and any(ord(ch) < 32 or ch in "{}" for ch in value):
            raise ValueError("search may not contain control characters or literals")
        return value

    @field_validator("allow")
    @classmethod
    def _allow_only_low_risk(cls, value: list[str]) -> list[str]:
        blocked = sorted(set(value) - API_ROUTINE_ALLOWABLE)
        if blocked:
            raise ValueError(f"these risk classes must stay gated (approve them per run): {blocked}")
        return value


class RoutineCreate(BaseModel):
    id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str | None = None
    kind: Literal["invoices", "task"] = "invoices"
    schedule: RoutineSchedule
    params: RoutineParams = Field(default_factory=RoutineParams)
    agent_id: str = "default"
    enabled: bool = True


class Routine(BaseModel):
    id: str
    name: str
    kind: str
    schedule: dict
    params: dict = Field(default_factory=dict)
    agent_id: str = "default"
    enabled: bool = True
    created_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    next_run_at: str | None = None


class RoutineRun(BaseModel):
    id: str
    routine_id: str
    started_at: str
    ended_at: str | None = None
    status: str | None = None
    detail: dict = Field(default_factory=dict)
    approval_id: str | None = None
    log_path: str | None = None


class RoutineEnable(BaseModel):
    enabled: bool = True


class SetupImap(BaseModel):
    host: str = "imap.gmail.com"
    user: str = Field(min_length=3)
    app_password: str = Field(min_length=8)


class SetupState(BaseModel):
    needs_setup: bool = True
    imap_configured: bool = False
    imap_user: str | None = None
    imap_host: str | None = None
    routines_count: int = 0
    daemon_running: bool = False
    version: str = "0.1.0-f5"
    # Creative tools found on this machine: name -> path, or None when missing.
    tools: dict[str, str | None] = Field(default_factory=dict)


class AgentCreate(BaseModel):
    """User-level agent written to ~/.eeze/agents.yaml (repo agents stay untouched)."""

    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=60)
    role: str = "generalist"
    description: str | None = None
    permissions: AgentPermissions = Field(default_factory=AgentPermissions)
    tools: list[str] = Field(default_factory=lambda: ["*"])
    model: dict = Field(default_factory=lambda: {"brain": "jev"})
    budget_usd_daily: float | None = Field(default=None, ge=0, le=1000)


class SpendAgent(BaseModel):
    agent_id: str
    spent_usd: float = 0.0
    tokens: int = 0
    calls: int = 0
    budget_usd: float | None = None  # effective daily cap (None = no cap)
    remaining_usd: float | None = None


class SpendToday(BaseModel):
    day: str
    total_usd: float
    agents: list[SpendAgent]


class ProviderRow(BaseModel):
    """One provider as the Settings page sees it (P2). The key VALUE is never part of this."""

    id: str
    label: str
    kind: Literal["api_key", "oauth_external", "local"]
    compatible: bool = True
    local_only: bool = False
    docs_url: str = ""
    note: str = ""
    brain: str = "llm"
    role: str = ""  # "model" = the provider the model layer resolves to; "engine" = brain running now
    base_url: str = ""
    base_url_source: str = "default"
    configured: bool | None = None
    configured_detail: str = ""
    key_source: str = "none"
    key_last4: str = ""
    key_in_store: bool = False
    models: dict[str, str] = Field(default_factory=dict)
    is_default: bool = False


class ProviderKeySet(BaseModel):
    key: str = Field(min_length=1, max_length=4096)


class ProviderOverride(BaseModel):
    base_url: str | None = None
    default_models: dict[str, str] | None = None
    set_default: bool | None = None


class ProbeResult(BaseModel):
    """Outcome of a LIVE connection test — real call, honest failure, never a key."""

    ok: bool
    provider_id: str
    method: str
    status_code: int | None = None
    latency_ms: float | None = None
    model_echo: str = ""
    tokens: int | None = None
    detail: str = ""


# ------------- missions (F7): write the goal, edit the plan, run it -------------


class MissionSchedule(BaseModel):
    """Mirrors the routines UI: on demand, daily at HH:MM, or every N minutes."""

    type: Literal["on_demand", "daily", "every"] = "on_demand"
    at: str | None = None
    minutes: int | None = None


class Mission(BaseModel):
    id: str
    name: str
    kind: str
    agent_id: str = "default"
    goal: str = ""
    schedule: dict = Field(default_factory=dict)
    sources: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    last_run: dict | None = None
    plan_meta: dict = Field(default_factory=dict)
    has_plan: bool = False
    plan_chars: int = 0
    plan: str | None = None
    note: str = ""  # what happened to the schedule on the last save (honest, never silent)


class MissionSave(BaseModel):
    id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str | None = None
    kind: Literal["3d", "video", "photo", "task", "files"] = "task"
    agent_id: str = "default"
    goal: str = ""
    plan: str | None = None  # None keeps the stored plan (partial updates are safe)
    sources: str | None = None
    schedule: MissionSchedule = Field(default_factory=MissionSchedule)


class MissionDraftRequest(BaseModel):
    kind: Literal["3d", "video", "photo", "task", "files"]
    goal: str = Field(min_length=1, max_length=4000)
    name: str | None = None
    sources: str | None = None
    agent_id: str | None = Field(default=None, max_length=40)  # whose daily budget pays


class MissionValidateRequest(BaseModel):
    plan: str = ""  # empty = validate the stored plan
    sources: str | None = None
    kind: Literal["3d", "video", "photo", "task", "files"] | None = None  # set = stateless check of a draft
