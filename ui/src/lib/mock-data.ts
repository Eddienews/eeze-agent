export type AgentStatus = "idle" | "working" | "needs_approval" | "error";
export type RiskLevel = "read" | "write" | "send" | "pay" | "exec";

export interface AgentMetrics {
  tasksToday: number;
  successRate: number | null; // null = no finished runs yet (never invent 0%)
  costToday: number;
  timeSaved?: string;
  runsTotal?: number;
  avgCycleMs?: number | null;
}

export interface Routine {
  id: string;
  name: string;
  schedule: string;
  enabled: boolean;
}

export interface MemoryNote {
  id: string;
  title: string;
  content: string;
  learnedAt: string;
}

export interface RunRecord {
  id: string;
  task: string;
  startedAt: string;
  duration: string;
  steps: number;
  cost: number;
  outcome: "running" | "success" | "failed" | "cancelled";
  runsetId?: string;
  journalUrl?: string;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  accent: string; // hue token, see styles.css agent accents
  status: AgentStatus;
  currentTask?: string;
  metrics: AgentMetrics;
  description?: string;
  personality?: string;
  model: string;
  plannerModel: string;
  autonomy: "suggest" | "approve" | "autonomous";
  source?: "repo" | "user";
  dailyBudget: number;
  permissions: { id: string; label: string; granted: boolean }[];
  tools: string[];
  routines: Routine[];
  memory: MemoryNote[];
  history: RunRecord[];
  createdAt?: string;
}

const perms = (granted: string[]) =>
  [
    { id: "browser", label: "Browser control" },
    { id: "files", label: "Local files" },
    { id: "email", label: "Send email" },
    { id: "calendar", label: "Calendar" },
    { id: "payments", label: "Payments" },
    { id: "terminal", label: "Terminal" },
  ].map((p) => ({ ...p, granted: granted.includes(p.id) }));

export const agents: Agent[] = [
  {
    id: "fin",
    name: "Fin",
    role: "Accounting & Finance",
    accent: "emerald",
    status: "working",
    currentTask: "Reconciling 42 invoices in Xero",
    metrics: { tasksToday: 12, successRate: 0.97, costToday: 1.84, timeSaved: "~4h" },
    description:
      "Handles bookkeeping, invoice reconciliation and expense categorisation across your finance tools.",
    personality: "Methodical, cautious with payments, and concise when reporting exceptions.",
    model: "claude-sonnet-4.6",
    plannerModel: "jev-planner-2",
    autonomy: "approve",
    dailyBudget: 12,
    permissions: [
      { id: "browser", label: "Read bank statements", granted: true },
      { id: "files", label: "Write to spreadsheets", granted: true },
      { id: "email", label: "Send emails", granted: true },
      { id: "calendar", label: "Access calendar", granted: false },
      { id: "payments", label: "Make payments", granted: false },
      { id: "terminal", label: "Use terminal", granted: false },
    ],
    tools: ["Xero", "Stripe", "Gmail", "Sheets", "PDF reader"],
    routines: [
      {
        id: "r1",
        name: "Download bank statements",
        schedule: "Every Monday at 8:00 AM",
        enabled: true,
      },
      {
        id: "r2",
        name: "Reconcile open invoices",
        schedule: "Every weekday at 9:30 AM",
        enabled: true,
      },
      {
        id: "r3",
        name: "Prepare quarterly VAT",
        schedule: "First day of each quarter",
        enabled: false,
      },
    ],
    memory: [
      {
        id: "m1",
        title: "Expense categorization",
        content: "Prefers to categorize software subscriptions under OpEx.",
        learnedAt: "3 days ago",
      },
      {
        id: "m2",
        title: "Reconciliation workflow",
        content: "Uses Xero for reconciliation and matches vendors by tax ID first.",
        learnedAt: "1 week ago",
      },
    ],
    history: [
      {
        id: "live",
        task: "Reconciling 42 invoices in Xero",
        startedAt: "Now",
        duration: "3m 48s",
        steps: 12,
        cost: 0.28,
        outcome: "running",
      },
      {
        id: "h1",
        task: "Reconcile March invoices",
        startedAt: "Today, 08:00",
        duration: "6m 12s",
        steps: 84,
        cost: 0.42,
        outcome: "success",
      },
      {
        id: "h2",
        task: "Categorise 18 card expenses",
        startedAt: "Yesterday, 17:20",
        duration: "2m 40s",
        steps: 31,
        cost: 0.18,
        outcome: "success",
      },
      {
        id: "h3",
        task: "Chase overdue payment — Nordwind",
        startedAt: "Yesterday, 10:05",
        duration: "1m 02s",
        steps: 12,
        cost: 0.07,
        outcome: "failed",
      },
    ],
    createdAt: "Mar 4, 2026",
  },
  {
    id: "inbox",
    name: "Inbox",
    role: "Email & Scheduling",
    accent: "violet",
    status: "needs_approval",
    currentTask: "Waiting on approval to send 2 replies",
    metrics: { tasksToday: 27, successRate: 0.94, costToday: 0.96, timeSaved: "~6h" },
    description:
      "Triages your mail, drafts replies in your voice and keeps the calendar free of collisions.",
    personality: "Warm, brief, and careful around legal or investor conversations.",
    model: "gpt-5.2-mini",
    plannerModel: "jev-planner-2",
    autonomy: "approve",
    dailyBudget: 8,
    permissions: perms(["browser", "email", "calendar"]),
    tools: ["Gmail", "Google Calendar", "Slack", "Notion"],
    routines: [
      { id: "r1", name: "Morning triage", schedule: "Every day at 07:30", enabled: true },
      { id: "r2", name: "Follow-up nudges", schedule: "Every 4 hours", enabled: true },
      { id: "r3", name: "Inbox zero sweep", schedule: "Fridays at 16:00", enabled: false },
    ],
    memory: [
      {
        id: "m1",
        title: "Tone",
        content: "Short, warm, no exclamation marks. Sign off with 'Best, Ana'.",
        learnedAt: "2 days ago",
      },
      {
        id: "m2",
        title: "Never auto-reply",
        content: "Legal and investor threads are always drafted, never sent.",
        learnedAt: "5 days ago",
      },
    ],
    history: [
      {
        id: "h1",
        task: "Triage 63 new emails",
        startedAt: "Today, 07:30",
        duration: "4m 05s",
        steps: 120,
        cost: 0.31,
        outcome: "success",
      },
      {
        id: "h2",
        task: "Reschedule design review",
        startedAt: "Today, 09:14",
        duration: "48s",
        steps: 9,
        cost: 0.04,
        outcome: "success",
      },
    ],
    createdAt: "Mar 8, 2026",
  },
  {
    id: "scout",
    name: "Scout",
    role: "Research & Monitoring",
    accent: "amber",
    status: "idle",
    metrics: { tasksToday: 4, successRate: 0.89, costToday: 0.42, timeSaved: "~2h" },
    description:
      "Watches competitors, sources and pricing pages, and writes up what actually changed.",
    personality: "Curious and evidence-led, with a preference for primary sources.",
    model: "gemini-3-pro",
    plannerModel: "jev-planner-2",
    autonomy: "autonomous",
    dailyBudget: 6,
    permissions: perms(["browser", "files"]),
    tools: ["Web browser", "RSS", "Notion", "Sheets"],
    routines: [
      { id: "r1", name: "Competitor pricing watch", schedule: "Every day at 06:00", enabled: true },
      { id: "r2", name: "Weekly market digest", schedule: "Fridays at 08:00", enabled: true },
    ],
    memory: [
      {
        id: "m1",
        title: "Tracked competitors",
        content: "Linear, Vercel, Slack, Raycast. Ignore press releases older than 14 days.",
        learnedAt: "1 day ago",
      },
    ],
    history: [
      {
        id: "h1",
        task: "Scan pricing pages",
        startedAt: "Today, 06:00",
        duration: "3m 22s",
        steps: 48,
        cost: 0.22,
        outcome: "success",
      },
      {
        id: "h2",
        task: "Summarise 9 industry posts",
        startedAt: "Yesterday, 06:00",
        duration: "5m 10s",
        steps: 61,
        cost: 0.2,
        outcome: "cancelled",
      },
    ],
    createdAt: "Mar 12, 2026",
  },
];

export interface Approval {
  id: string;
  agentId: string;
  action: string;
  context: string;
  preview: string;
  risk: RiskLevel;
  requestedAt: string;
}

export const approvals: Approval[] = [
  {
    id: "a1",
    agentId: "inbox",
    action: "Send email to cliente@empresa.com",
    context: "Reply to 'Proposal follow-up' — thread has been idle for 4 days.",
    preview:
      "Hi Marco,\n\nThanks for the patience. The revised proposal is attached with the updated scope and the new timeline for April.\n\nBest,\nAna",
    risk: "send",
    requestedAt: "6 min ago",
  },
  {
    id: "a2",
    agentId: "fin",
    action: "Pay invoice INV-2291 — €2,480.00",
    context: "Above the €2,000 approval threshold. Vendor: ACME BV, due tomorrow.",
    preview: "Stripe transfer · ACME BV · EUR 2,480.00 · reference INV-2291",
    risk: "pay",
    requestedAt: "22 min ago",
  },
  {
    id: "a3",
    agentId: "fin",
    action: "Overwrite Q1 reconciliation sheet",
    context: "14 rows changed after matching bank feed to Xero entries.",
    preview: "Sheet: Finance / Q1-2026 reconciliation · 14 cells modified, 0 deleted",
    risk: "write",
    requestedAt: "1 h ago",
  },
  {
    id: "a4",
    agentId: "scout",
    action: "Access competitor billing portal",
    context: "Needs a logged-in session to read the current enterprise tier pricing.",
    preview: "Read-only browsing session · linear.app/settings/billing",
    risk: "read",
    requestedAt: "2 h ago",
  },
];

export const getAgent = (id: string) => agents.find((a) => a.id === id);

export const statusLabel: Record<AgentStatus, string> = {
  idle: "Idle",
  working: "Working",
  needs_approval: "Needs approval",
  error: "Error",
};

export const riskLabel: Record<RiskLevel, string> = {
  read: "Read",
  write: "Write",
  send: "Send",
  pay: "Pay",
  exec: "Install / exec",
};
