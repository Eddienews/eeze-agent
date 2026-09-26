import {
  agents as mockAgents,
  approvals as mockApprovals,
  getAgent as getMockAgent,
  type Agent,
  type AgentStatus,
  type Approval,
  type RiskLevel,
  type RunRecord,
} from "@/lib/mock-data";
import { redirectToPair } from "@/lib/pairing";

/**
 * Same-origin API prefix. In dev, Vite proxies /api -> http://127.0.0.1:8765
 * (see vite.config.ts); in production FastAPI serves both the SPA and the API
 * on the same host, so a relative prefix works in both modes.
 */
export const API_URL = "/api";

/**
 * Public preview mode (eeze.app): the site ships with `VITE_DEMO_MODE=true`, so
 * every call below resolves to the bundled sample data — the demo never touches
 * a network API (the real app runs on the user's machine).
 */
export const DEMO_MODE = import.meta.env["VITE_DEMO_MODE"] === "true";

/** Raw shapes exposed by the read-only backend. */
export interface ApiAgentMetrics {
  runs_total?: number;
  runs_24h?: number;
  success_rate?: number;
  avg_cycle_ms?: number;
  cost_usd?: number;
}

export interface ApiAgent {
  id: string;
  name: string;
  role: string;
  description?: string | null;
  avatar_color?: string;
  status?: string;
  paused?: boolean;
  current_run_id?: string | null;
  current_task?: string | null;
  metrics?: ApiAgentMetrics;
  model?: string | { brain?: string | null; planner?: string | null };
  budget_usd_daily?: number | null;
  permissions?:
    | Array<string | { id: string; label?: string; granted?: boolean }>
    | { risk_classes?: string[]; apps?: string[]; allow_foreground?: boolean };
  tools?: string[];
  created_at?: string | null;
  source?: string;
}

export interface AgentCreateRequest {
  id: string;
  name: string;
  role?: string;
  description?: string;
  permissions?: { risk_classes?: string[]; apps?: string[]; allow_foreground?: boolean };
  tools?: string[];
  model?: { brain?: string };
}

export interface ApiJudgment {
  kind?: string;
  question?: string;
  answer?: string;
  confidence?: number;
  ms?: number;
}

export interface ApiRunStep {
  id: string | number;
  index?: number;
  action?: string;
  intent?: string;
  selected?: string;
  target?: string;
  write_method?: string | null;
  verification?: string | null;
  ok?: boolean;
  status?: string;
  ms?: number;
  judgment?: ApiJudgment | null;
  confidence?: number;
  judgment_question?: string;
  judgment_answer?: string;
  artifacts?: string[];
  screenshot_url?: string;
  ts?: string;
}

export interface ApiRun {
  id: string;
  runset_id?: string;
  agent_id: string;
  task_name: string;
  status?: string;
  started_at?: string;
  ended_at?: string;
  cycle_ms?: number;
  duration_s?: number;
  cost_usd?: number | null;
  interference?: boolean;
  error?: string | null;
  steps?: ApiRunStep[];
  journal_url?: string;
  interference_events?: unknown[];
}

export interface ApiApproval {
  id: string;
  agent_id: string;
  action?: string;
  context?: string;
  risk?: string;
  preview?: string;
  created_at?: string;
  // F2 approval-store shape
  title?: string;
  step_id?: string;
  risk_class?: string;
  run_id?: string;
  payload_preview?: Record<string, unknown>;
  requested_at?: string;
  status?: string;
}

export interface ApiApprovalQueueItem {
  id: string;
  agent_id: string;
  run_id: string;
  step_id: string;
  title: string;
  risk_class: string;
  payload_preview: Record<string, unknown>;
  requested_at?: string;
  status: string;
  resumable: boolean;
}

export interface ApiGrant {
  id: string;
  agent_id: string;
  risk_class: string;
  scope: string;
  task?: string | null;
  created_at?: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  status: string;
}

export interface ApprovalDecisionRequest {
  decision: "approve" | "deny" | "abandon";
  grant?: { scope: "task" | "agent"; ttl_hours?: number };
  auto_resume?: boolean;
  reason?: string;
}

export interface ApprovalDecisionResponse {
  ok: boolean;
  approval: ApiApprovalQueueItem;
  grant_id: string | null;
  resumed: boolean;
  resume_log: string | null;
}

export interface ApiSystemStatus {
  daemon?: string | { running?: boolean; pid?: number; permission_mode?: string };
  daemon_status?: string;
  jev?: string | { calls?: number; latency_ms_p50?: number; cost_usd?: number; model?: string };
  jev_status?: string;
  agents?: ApiAgent[];
  agents_count?: number;
  runs_total?: number;
  interference_events?: number;
  notifications_enabled?: boolean;
  routine_failure_notifications_enabled?: boolean;
  version?: string;
}

export interface ApiSystemInfo {
  version?: string;
  python?: string;
  daemon?: string | { running?: boolean; pid?: number; host?: string; port?: number };
  api_pid?: number;
  store_path?: string;
  token_path?: string;
  user_agents_path?: string;
  repo_agents_path?: string;
  artifacts_path?: string;
  keys?: Record<string, boolean>;
  runsets?: number;
  backups?: number;
}

export interface ApiSetupState {
  needs_setup: boolean;
  imap_configured: boolean;
  imap_user?: string | null;
  imap_host?: string | null;
  routines_count: number;
  daemon_running: boolean;
  version: string;
  tools?: Record<string, string | null>;
}

export interface ImapSetupRequest {
  host: string;
  user: string;
  app_password: string;
}

export interface ApiRoutineSchedule {
  type: "daily" | "every";
  at?: string | null;
  minutes?: number | null;
}

export interface ApiRoutineParams {
  search?: string;
  email_summary?: boolean;
  email_to?: string;
  task_path?: string;
  runs?: number;
  demo?: boolean;
  allow?: string[];
}

export interface ApiRoutine {
  id: string;
  name: string;
  kind: string;
  schedule: ApiRoutineSchedule;
  params: ApiRoutineParams;
  agent_id: string;
  enabled: boolean;
  created_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  next_run_at?: string | null;
}

export interface RoutineCreateRequest {
  id: string;
  name?: string;
  kind: "invoices" | "task";
  schedule: ApiRoutineSchedule;
  params?: ApiRoutineParams;
  agent_id?: string;
  enabled?: boolean;
}

export interface ApiRoutineRun {
  id: string;
  routine_id: string;
  started_at: string;
  ended_at?: string | null;
  status?: string | null;
  detail?: Record<string, unknown>;
  approval_id?: string | null;
  log_path?: string | null;
}

/* --------------------------------- missions (F7) --------------------------------- */

export type MissionKind = "3d" | "video" | "photo" | "task" | "files";

export interface ApiMissionSchedule {
  type: "on_demand" | "daily" | "every";
  at?: string | null;
  minutes?: number | null;
}

export interface ApiMissionRun {
  runset_id: string;
  status: string;
  approval_id?: string | null;
  out_dir?: string;
  at?: string;
}

export interface ApiMission {
  id: string;
  name: string;
  kind: MissionKind;
  agent_id: string;
  goal: string;
  schedule: ApiMissionSchedule;
  sources: string;
  created_at?: string | null;
  updated_at?: string | null;
  last_run?: ApiMissionRun | null;
  plan_meta: {
    model?: string;
    tokens?: number;
    cost_usd?: number | null;
    ms?: number;
    edited?: boolean;
  };
  has_plan: boolean;
  plan_chars: number;
  plan?: string | null;
  note?: string;
}

export interface ApiRecipe {
  id: string;
  title: string;
  kind: MissionKind;
  needs_sources: boolean;
  name: string;
  goal: string;
  blurb: string;
  title_pt?: string;
  name_pt?: string;
  goal_pt?: string;
  blurb_pt?: string;
}

export interface ApiMediaFile {
  name: string;
  kind: "image" | "video" | "model" | "other";
  size: number;
  url: string;
  step?: boolean; // intermediate step output, not the deliverable
}

export interface ApiFsListing {
  path: string;
  parent: string | null;
  dirs: string[];
  files: Array<{ name: string; path: string }>;
  media_count: number;
  truncated: boolean;
  places: Array<{ label: string; path: string }>;
}

export interface ApiFileChange {
  from: string;
  to: string;
}

export interface ApiFilesReport {
  op?: string;
  folder?: string;
  files?: number;
  applied?: number;
  undone?: boolean;
  duplicates?: string[][];
  conflicts?: string[];
  error?: string | null;
  changes?: ApiFileChange[];
}

export interface ApiFilesPreview extends ApiFilesReport {
  ok: boolean;
  total_changes?: number;
}

export interface ApiMissionOutputs {
  status: string | null;
  runset_id: string | null;
  report?: ApiFilesReport | null;
  files: ApiMediaFile[];
  sources: ApiMediaFile[];
}

export interface MissionSaveRequest {
  id: string;
  name?: string;
  kind: MissionKind;
  agent_id?: string;
  goal?: string;
  plan?: string;
  sources?: string;
  schedule?: ApiMissionSchedule;
}

export interface MissionDraftResult {
  plan: string;
  plan_kind: string;
  model: string;
  attempts: Array<{ attempt: number; ms?: number; tokens?: number; error: string | null }>;
  tokens: number;
  cost_usd: number | null;
  ms: number;
}

/** A model provider as Settings needs it (P2/P3). The key VALUE is never part of this. */
export interface ApiProvider {
  id: string;
  label: string;
  kind: "api_key" | "oauth_external" | "local";
  compatible: boolean;
  local_only: boolean;
  docs_url: string;
  note: string;
  brain: "llm" | "codex";
  role: "model" | "engine" | "";
  base_url: string;
  base_url_source: "run" | "agent" | "store" | "env" | "default";
  configured: boolean | null;
  configured_detail: string;
  key_source: "store" | "env" | "none";
  key_last4: string;
  key_in_store: boolean;
  models: { routine?: string; hard?: string };
  is_default: boolean;
}

/** Result of a LIVE connection test — real numbers, honest failure. */
export interface ApiProbeResult {
  ok: boolean;
  provider_id: string;
  method: string;
  status_code: number | null;
  latency_ms: number | null;
  model_echo: string;
  tokens: number | null;
  detail: string;
}

export interface ProviderOverrideRequest {
  base_url?: string;
  default_models?: Record<string, string>;
  set_default?: boolean;
}

export class ApiUnreachableError extends Error {
  constructor(message = "API unreachable") {
    super(message);
    this.name = "ApiUnreachableError";
  }
}

/** The backend wraps collections in { items, total, limit, offset }. */
function unwrap<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[];
  const items = (payload as { items?: unknown })?.items;
  return Array.isArray(items) ? (items as T[]) : [];
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (DEMO_MODE) {
    throw new Error("demo mode: network access disabled");
  }
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      ...(signal ? { signal } : {}),
    });
  } catch {
    throw new ApiUnreachableError(`Could not reach ${API_URL}`);
  }
  if (response.status === 401) redirectToPair();
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

/** Shape of the API's error envelope (see the backend exception handler). */
export interface ApiErrorEnvelope {
  code?: string;
  message?: string;
  detail?: unknown;
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  if (DEMO_MODE) throw new Error("demo mode: writes disabled");
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (response.status === 401) redirectToPair();
  if (!response.ok) {
    let detail = `${response.status}`;
    let envelope: ApiErrorEnvelope | null = null;
    try {
      const payload = (await response.json()) as { error?: ApiErrorEnvelope };
      envelope = payload?.error ?? null;
      detail = envelope?.message ?? detail;
    } catch {
      /* keep the status text */
    }
    // The envelope rides along (status + structured detail, e.g. the spec writer's attempts) so a
    // screen can show WHY instead of a bare string.
    const error = new Error(`${path}: ${detail}`) as Error & {
      status?: number;
      envelope?: ApiErrorEnvelope | null;
    };
    error.status = response.status;
    error.envelope = envelope;
    throw error;
  }
  return (await response.json()) as T;
}

/* ---------------------------------- mappers --------------------------------- */

const statusMap: Record<string, AgentStatus> = {
  idle: "idle",
  working: "working",
  running: "working",
  busy: "working",
  needs_approval: "needs_approval",
  awaiting_approval: "needs_approval",
  error: "error",
  failed: "error",
};

const riskMap: Record<string, RiskLevel> = {
  read: "read",
  write: "write",
  write_local: "write",
  write_remote: "write",
  send: "send",
  pay: "pay",
  external_send: "send",
  install_exec: "exec",
  destructive: "pay",
  system: "exec",
};

const outcomeMap: Record<string, RunRecord["outcome"]> = {
  ok: "success",
  running: "running",
  in_progress: "running",
  success: "success",
  completed: "success",
  failed: "failed",
  error: "failed",
  cancelled: "cancelled",
  canceled: "cancelled",
};

const accents = ["emerald", "violet", "amber", "sky", "rose", "slate"];

const accentFor = (agent: ApiAgent, index: number) =>
  agent.avatar_color && accents.includes(agent.avatar_color)
    ? agent.avatar_color
    : (accents[index % accents.length] as string);

const titleize = (value: string) =>
  value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());

function formatDuration(seconds?: number) {
  if (!seconds && seconds !== 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

function formatStarted(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function mapPermissions(raw: ApiAgent["permissions"]) {
  if (!raw) return null;
  if (Array.isArray(raw)) {
    if (!raw.length) return null;
    return raw.map((permission, index) =>
      typeof permission === "string"
        ? { id: permission, label: titleize(permission), granted: true }
        : {
            id: permission.id ?? `permission-${index}`,
            label: permission.label ?? titleize(permission.id ?? `permission-${index}`),
            granted: permission.granted ?? true,
          },
    );
  }
  const list = (raw.risk_classes ?? []).map((item) => ({
    id: item,
    label: titleize(item),
    granted: true,
  }));
  if (raw.apps?.length) {
    list.push({
      id: "apps",
      label: raw.apps.includes("*") ? "All applications" : raw.apps.join(", "),
      granted: true,
    });
  }
  list.push({
    id: "allow_foreground",
    label: "Foreground control",
    granted: Boolean(raw.allow_foreground),
  });
  return list.length ? list : null;
}

export function mapAgent(raw: ApiAgent, index = 0): Agent {
  const fallback =
    mockAgents.find((agent) => agent.id === raw.id) ?? mockAgents[index % mockAgents.length]!;
  // mock-only profile fields must not leak into live agents
  const {
    currentTask: _fallbackTask,
    personality: _fallbackPersonality,
    description: _fallbackDescription,
    ...fallbackRest
  } = fallback;
  const metrics = raw.metrics ?? {};
  const rawRate = metrics.success_rate ?? null;
  const successRate = rawRate === null ? null : rawRate > 1 ? rawRate / 100 : rawRate;
  const model = typeof raw.model === "string" ? raw.model : (raw.model?.brain ?? fallback.model);
  const plannerModel =
    typeof raw.model === "object" && raw.model?.planner ? raw.model.planner : fallback.plannerModel;
  const tools = raw.tools?.length
    ? raw.tools.map((tool) => (tool === "*" ? "All tools" : tool))
    : fallback.tools;

  return {
    ...fallbackRest,
    id: raw.id,
    name: raw.name,
    role: raw.role,
    accent: accentFor(raw, index),
    status: raw.paused ? "idle" : (statusMap[raw.status ?? ""] ?? "idle"),
    ...(raw.current_task ? { currentTask: raw.current_task } : {}),
    ...(raw.description ? { description: raw.description } : {}),
    metrics: {
      tasksToday: metrics.runs_24h ?? metrics.runs_total ?? 0,
      successRate,
      costToday: metrics.cost_usd ?? 0,
      runsTotal: metrics.runs_total ?? 0,
      avgCycleMs: metrics.avg_cycle_ms ?? null,
    },
    routines: [],
    memory: [],
    model,
    plannerModel,
    dailyBudget: raw.budget_usd_daily ?? fallback.dailyBudget,
    permissions: mapPermissions(raw.permissions) ?? fallback.permissions,
    tools,
    createdAt: raw.created_at ? formatStarted(raw.created_at) : (fallback.createdAt ?? "—"),
    ...(raw.source === "user" || raw.source === "repo"
      ? { source: raw.source as "repo" | "user" }
      : {}),
  };
}

export function mapRun(raw: ApiRun): RunRecord {
  const seconds = raw.duration_s ?? (raw.cycle_ms !== undefined ? raw.cycle_ms / 1000 : undefined);
  return {
    id: raw.id,
    task: raw.task_name,
    startedAt: formatStarted(raw.started_at),
    duration: formatDuration(seconds),
    steps: raw.steps?.length ?? 0,
    cost: raw.cost_usd ?? 0,
    outcome: outcomeMap[(raw.status ?? "").toLowerCase()] ?? "success",
    ...(raw.runset_id ? { runsetId: raw.runset_id } : {}),
    ...(raw.journal_url ? { journalUrl: raw.journal_url } : {}),
  };
}

export function mapApproval(raw: ApiApproval): Approval {
  const previewText =
    raw.preview ??
    (raw.payload_preview && Object.keys(raw.payload_preview).length
      ? JSON.stringify(raw.payload_preview, null, 2)
      : "");
  return {
    id: raw.id,
    agentId: raw.agent_id,
    action: raw.action ?? raw.title ?? "Approval requested",
    context: raw.context ?? (raw.status && raw.status !== "pending" ? `Status: ${raw.status}` : ""),
    preview: previewText,
    risk: riskMap[raw.risk ?? raw.risk_class ?? ""] ?? "write",
    requestedAt: raw.requested_at ?? raw.created_at ?? "just now",
  };
}

/* --------------------------------- endpoints -------------------------------- */

export interface RunFilters {
  agent_id?: string;
  status?: string;
  task_name?: string;
  interference?: boolean;
}

export interface ApiSpendAgent {
  agent_id: string;
  spent_usd: number;
  tokens: number;
  calls: number;
  budget_usd: number | null;
  remaining_usd: number | null;
}

export interface ApiSpendToday {
  day: string;
  total_usd: number;
  agents: ApiSpendAgent[];
}

export const api = {
  spendToday: (signal?: AbortSignal): Promise<ApiSpendToday> =>
    DEMO_MODE
      ? Promise.resolve({ day: "", total_usd: 0, agents: [] })
      : get<ApiSpendToday>("/spend/today", signal),
  health: (signal?: AbortSignal) =>
    DEMO_MODE ? Promise.resolve({ ok: true }) : get<unknown>("/system/status", signal),
  agents: async (signal?: AbortSignal) =>
    DEMO_MODE
      ? fallbacks.agents
      : unwrap<ApiAgent>(await get<unknown>("/agents", signal)).map(mapAgent),
  agent: async (id: string, signal?: AbortSignal) =>
    DEMO_MODE
      ? (getMockAgent(id) ?? fallbacks.agents[0]!)
      : mapAgent(await get<ApiAgent>(`/agents/${id}`, signal)),
  runs: async (filters: RunFilters = {}, signal?: AbortSignal) => {
    if (DEMO_MODE) return fallbacks.runs;
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== "" && value !== "all") params.set(key, String(value));
    });
    const query = params.toString();
    const raw = unwrap<ApiRun>(await get<unknown>(`/runs${query ? `?${query}` : ""}`, signal));
    return raw.map(mapRun);
  },
  run: async (id: string, signal?: AbortSignal): Promise<ApiRun> =>
    DEMO_MODE ? demoRun(id) : get<ApiRun>(`/runs/${encodeURIComponent(id)}`, signal),
  approvals: async (signal?: AbortSignal) =>
    DEMO_MODE
      ? fallbacks.approvals
      : unwrap<ApiApproval>(await get<unknown>("/approvals", signal)).map(mapApproval),
  approvalQueue: async (status?: string, signal?: AbortSignal): Promise<ApiApprovalQueueItem[]> => {
    if (DEMO_MODE) return [];
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return unwrap<ApiApprovalQueueItem>(await get<unknown>(`/approvals${query}`, signal));
  },
  decideApproval: (id: string, body: ApprovalDecisionRequest): Promise<ApprovalDecisionResponse> =>
    send<ApprovalDecisionResponse>(`/approvals/${encodeURIComponent(id)}/decide`, "POST", body),
  grants: async (signal?: AbortSignal): Promise<ApiGrant[]> => {
    if (DEMO_MODE) return [];
    return unwrap<ApiGrant>(await get<unknown>("/grants", signal));
  },
  revokeGrant: (id: string): Promise<{ ok: boolean; grant_id: string; status: string }> =>
    send<{ ok: boolean; grant_id: string; status: string }>(
      `/grants/${encodeURIComponent(id)}`,
      "DELETE",
    ),
  systemStatus: (signal?: AbortSignal): Promise<ApiSystemStatus> =>
    DEMO_MODE
      ? Promise.resolve({
          daemon: { running: true },
          agents: [],
          runs_total: 0,
          interference_events: 0,
        })
      : get<ApiSystemStatus>("/system/status", signal),
  systemInfo: (signal?: AbortSignal): Promise<ApiSystemInfo> =>
    DEMO_MODE
      ? Promise.resolve({ version: "demo", python: "—", daemon: { running: true } })
      : get<ApiSystemInfo>("/system/info", signal),
  routines: async (signal?: AbortSignal): Promise<ApiRoutine[]> => {
    if (DEMO_MODE) return [];
    return unwrap<ApiRoutine>(await get<unknown>("/routines", signal));
  },
  createRoutine: (body: RoutineCreateRequest): Promise<ApiRoutine> =>
    send<ApiRoutine>("/routines", "POST", body),
  setRoutineEnabled: (
    id: string,
    enabled: boolean,
  ): Promise<{ ok: boolean; id: string; enabled: boolean }> =>
    send<{ ok: boolean; id: string; enabled: boolean }>(
      `/routines/${encodeURIComponent(id)}/enable`,
      "POST",
      { enabled },
    ),
  runRoutineNow: (
    id: string,
  ): Promise<{ ok: boolean; id: string; spawned: boolean; log: string }> =>
    send<{ ok: boolean; id: string; spawned: boolean; log: string }>(
      `/routines/${encodeURIComponent(id)}/run`,
      "POST",
    ),
  removeRoutine: (id: string): Promise<{ ok: boolean; id: string }> =>
    send<{ ok: boolean; id: string }>(`/routines/${encodeURIComponent(id)}`, "DELETE"),
  routineRuns: async (id: string, signal?: AbortSignal): Promise<ApiRoutineRun[]> => {
    if (DEMO_MODE) return [];
    return unwrap<ApiRoutineRun>(
      await get<unknown>(`/routines/${encodeURIComponent(id)}/runs`, signal),
    );
  },
  missions: async (signal?: AbortSignal): Promise<ApiMission[]> => {
    if (DEMO_MODE) return [];
    return unwrap<ApiMission>(await get<unknown>("/missions", signal));
  },
  mission: (id: string, signal?: AbortSignal): Promise<ApiMission> =>
    get<ApiMission>(`/missions/${encodeURIComponent(id)}`, signal),
  draftMission: (body: {
    kind: MissionKind;
    goal: string;
    name?: string;
    sources?: string;
    agent_id?: string;
  }): Promise<MissionDraftResult> => send<MissionDraftResult>("/missions/draft", "POST", body),
  saveMission: (body: MissionSaveRequest): Promise<ApiMission> =>
    send<ApiMission>("/missions", "POST", body),
  removeMission: (
    id: string,
  ): Promise<{ ok: boolean; removed: boolean; routine_removed: boolean }> =>
    send<{ ok: boolean; removed: boolean; routine_removed: boolean }>(
      `/missions/${encodeURIComponent(id)}`,
      "DELETE",
    ),
  /** Stateless check of a draft (no mission id yet) — the runner's own loaders decide. */
  validateDraft: (body: {
    kind: MissionKind;
    plan: string;
    sources?: string;
  }): Promise<{ ok: boolean; errors: string[] }> =>
    send<{ ok: boolean; errors: string[] }>("/missions/validate", "POST", body),
  validateMission: (
    id: string,
    body: { plan?: string; sources?: string },
  ): Promise<{ ok: boolean; errors: string[] }> =>
    send<{ ok: boolean; errors: string[] }>(
      `/missions/${encodeURIComponent(id)}/validate`,
      "POST",
      body,
    ),
  recipes: async (signal?: AbortSignal): Promise<ApiRecipe[]> =>
    DEMO_MODE ? [] : unwrap<ApiRecipe>(await get<unknown>("/recipes", signal)),
  describePlan: (kind: MissionKind, plan: string, lang = "en"): Promise<{ lines: string[] }> =>
    DEMO_MODE
      ? Promise.resolve({ lines: [] })
      : send<{ lines: string[] }>(`/missions/describe?lang=${lang}`, "POST", { kind, plan }),
  freshness: (
    signal?: AbortSignal,
  ): Promise<{ update_ready: boolean; service_stale: boolean; ui_stale: boolean }> =>
    get<{ update_ready: boolean; service_stale: boolean; ui_stale: boolean }>(
      "/system/freshness",
      signal,
    ),
  fsList: (path: string | null, files: boolean, signal?: AbortSignal): Promise<ApiFsListing> =>
    get<ApiFsListing>(
      `/fs/list?files=${files ? "true" : "false"}${path ? `&path=${encodeURIComponent(path)}` : ""}`,
      signal,
    ),
  filesPreview: (plan: string): Promise<ApiFilesPreview> =>
    send<ApiFilesPreview>("/files/preview", "POST", { plan }),
  undoMission: (id: string): Promise<{ ok: boolean; restored: number; folder: string }> =>
    send<{ ok: boolean; restored: number; folder: string }>(
      `/missions/${encodeURIComponent(id)}/undo`,
      "POST",
    ),
  missionOutputs: (id: string, signal?: AbortSignal): Promise<ApiMissionOutputs> =>
    get<ApiMissionOutputs>(`/missions/${encodeURIComponent(id)}/outputs`, signal),
  runMission: (id: string): Promise<{ ok: boolean; id: string; spawned: boolean; log: string }> =>
    send<{ ok: boolean; id: string; spawned: boolean; log: string }>(
      `/missions/${encodeURIComponent(id)}/run`,
      "POST",
    ),
  setupState: (signal?: AbortSignal): Promise<ApiSetupState> =>
    DEMO_MODE
      ? Promise.resolve({
          needs_setup: false,
          imap_configured: false,
          routines_count: 0,
          daemon_running: true,
          version: "demo",
        })
      : get<ApiSetupState>("/setup/state", signal),
  saveImap: (body: ImapSetupRequest): Promise<{ ok: boolean }> =>
    send<{ ok: boolean }>("/setup/imap", "POST", body),
  testImap: (body: ImapSetupRequest): Promise<{ ok: boolean; error?: string; messages?: number }> =>
    send<{ ok: boolean; error?: string; messages?: number }>("/setup/imap/test", "POST", body),
  completeSetup: (): Promise<{ ok: boolean }> => send<{ ok: boolean }>("/setup/complete", "POST"),
  setNotify: (enabled: boolean): Promise<{ ok: boolean; enabled: boolean }> =>
    send<{ ok: boolean; enabled: boolean }>("/setup/notify", "POST", { enabled }),
  setNotifyRoutines: (enabled: boolean): Promise<{ ok: boolean; enabled: boolean }> =>
    send<{ ok: boolean; enabled: boolean }>("/setup/notify-routines", "POST", { enabled }),
  createAgent: (body: AgentCreateRequest): Promise<ApiAgent> =>
    send<ApiAgent>("/agents", "POST", body),
  removeAgent: (id: string): Promise<{ ok: boolean; id: string }> =>
    send<{ ok: boolean; id: string }>(`/agents/${encodeURIComponent(id)}`, "DELETE"),
  providers: async (signal?: AbortSignal): Promise<ApiProvider[]> => {
    if (DEMO_MODE) return [];
    return unwrap<ApiProvider>(await get<unknown>("/providers", signal));
  },
  setProviderKey: (
    id: string,
    key: string,
  ): Promise<{ ok: boolean; id: string; key_last4: string }> =>
    send<{ ok: boolean; id: string; key_last4: string }>(
      `/providers/${encodeURIComponent(id)}/key`,
      "POST",
      { key },
    ),
  removeProviderKey: (id: string): Promise<{ ok: boolean; id: string; removed: boolean }> =>
    send<{ ok: boolean; id: string; removed: boolean }>(
      `/providers/${encodeURIComponent(id)}/key`,
      "DELETE",
    ),
  updateProvider: (id: string, body: ProviderOverrideRequest): Promise<ApiProvider> =>
    send<ApiProvider>(`/providers/${encodeURIComponent(id)}`, "PUT", body),
  testProvider: (id: string): Promise<ApiProbeResult> =>
    send<ApiProbeResult>(`/providers/${encodeURIComponent(id)}/test`, "POST"),
};

/** Minimal raw run from the sample data (the viewer supplies its own rich steps). */
function demoRun(id: string): ApiRun {
  for (const agent of mockAgents) {
    const run = agent.history.find((item) => item.id === id);
    if (run) {
      return {
        id: run.id,
        agent_id: agent.id,
        task_name: run.task,
        status: run.outcome === "success" ? "ok" : run.outcome,
        cost_usd: run.cost,
        steps: [],
      };
    }
  }
  return {
    id,
    agent_id: mockAgents[0]!.id,
    task_name: id,
    status: "ok",
    steps: [],
  };
}

/** Mock fallbacks so the design stays reviewable without a backend running. */
export const fallbacks = {
  agents: mockAgents,
  approvals: mockApprovals,
  runs: mockAgents.flatMap((agent) => agent.history),
};
