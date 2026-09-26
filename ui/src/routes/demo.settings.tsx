import { useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  AlertTriangle,
  Archive,
  BookOpen,
  Braces,
  Chrome,
  Copy,
  CreditCard,
  FileText,
  Gauge,
  KeyRound,
  Mail,
  OctagonX,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Slack,
  Sparkles,
  Table2,
  Trash2,
  WalletCards,
} from "lucide-react";
import { AgentAvatar } from "@/components/agent-avatar";
import { useStore } from "@/components/app-store";
import { CreateAgentWizard } from "@/components/create-agent-wizard";
import { StatusBadge } from "@/components/status-badge";
import { TypedConfirmDialog } from "@/components/typed-confirm-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorState, RefreshButton } from "@/components/data-state";
import { ProvidersCard } from "@/components/providers-card";
import { setupStateQuery, systemInfoQuery, systemStatusQuery } from "@/lib/queries";
import { API_URL, DEMO_MODE, api } from "@/lib/api";
import { createZip, downloadBlob } from "@/lib/zip";
import {} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { statusLabel, type Agent, type AgentStatus } from "@/lib/mock-data";

export const Route = createFileRoute("/demo/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Eeze Agents" },
      {
        name: "description",
        content:
          "Manage your Eeze Agents team, integrations, security, billing, and local system health.",
      },
      { property: "og:title", content: "Settings — Eeze Agents" },
      {
        property: "og:description",
        content: "Manage agents, connected services, security, billing, and runtime health.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: SettingsPage,
});

const integrations = [
  { name: "Xero", icon: BookOpen, connected: true, lastUsed: "4 min ago" },
  { name: "Stripe", icon: CreditCard, connected: true, lastUsed: "22 min ago" },
  { name: "Gmail", icon: Mail, connected: true, lastUsed: "6 min ago" },
  { name: "Google Sheets", icon: Table2, connected: true, lastUsed: "1 h ago" },
  { name: "Slack", icon: Slack, connected: false, lastUsed: "Never" },
  { name: "Notion", icon: FileText, connected: true, lastUsed: "Yesterday" },
  { name: "PDF reader", icon: FileText, connected: true, lastUsed: "Today" },
  { name: "Browser profiles", icon: Chrome, connected: false, lastUsed: "Never" },
];

const spend = [
  { month: "Apr", amount: 38 },
  { month: "May", amount: 52 },
  { month: "Jun", amount: 47 },
  { month: "Jul", amount: 71 },
  { month: "Aug", amount: 86 },
  { month: "Sep", amount: 64 },
];

const redactionOptions: Array<{
  id: string;
  label: string;
  detail: string;
  defaultChecked: boolean;
}> = [
  {
    id: "emails",
    label: "Redact emails",
    detail: "Mask email addresses in captured data.",
    defaultChecked: false,
  },
  {
    id: "amounts",
    label: "Redact financial amounts",
    detail: "Hide balances, totals, and transaction values.",
    defaultChecked: false,
  },
  {
    id: "keys",
    label: "Redact API keys",
    detail: "Detect and remove credentials from logs.",
    defaultChecked: true,
  },
];

function SettingsPage() {
  if (!DEMO_MODE) return <LiveSettings />;
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage your team, connected services, safety, and local runtime.
        </p>
      </div>
      <Tabs defaultValue="team" className="mt-6">
        <div className="overflow-x-auto pb-1">
          <TabsList className="w-max min-w-full justify-start sm:min-w-0">
            {["team", "integrations", "security", "billing", "system"].map((tab) => (
              <TabsTrigger key={tab} value={tab} className="capitalize">
                {tab}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value="team">
          <TeamSettings />
        </TabsContent>
        <TabsContent value="integrations">
          <IntegrationsSettings />
        </TabsContent>
        <TabsContent value="security">
          <SecuritySettings />
        </TabsContent>
        <TabsContent value="billing">
          <BillingSettings />
        </TabsContent>
        <TabsContent value="system">
          <SystemSettings />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function TeamSettings() {
  const { agents, addAgent, removeAgent } = useStore();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<AgentStatus | "all">("all");
  const [role, setRole] = useState("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [archiveAgent, setArchiveAgent] = useState<Agent | null>(null);
  const roles = [...new Set(agents.map((agent) => agent.role))];
  const visible = useMemo(
    () =>
      agents.filter(
        (agent) =>
          (status === "all" || agent.status === status) &&
          (role === "all" || agent.role === role) &&
          `${agent.name} ${agent.role}`.toLowerCase().includes(query.trim().toLowerCase()),
      ),
    [agents, query, role, status],
  );
  const duplicate = (agent: Agent) => {
    const { currentTask: _currentTask, ...copy } = agent;
    addAgent({
      ...copy,
      id: `${agent.id}-copy-${Date.now()}`,
      name: `${agent.name} Copy`,
      status: "idle",
      createdAt: "Today",
    });
    toast.success(`${agent.name} duplicated`);
  };

  return (
    <div className="mt-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search agents"
            aria-label="Search agents"
            className="pl-9"
          />
        </div>
        <Select value={status} onValueChange={(value) => setStatus(value as AgentStatus | "all")}>
          <SelectTrigger className="w-full sm:w-44" aria-label="Filter agents by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {Object.entries(statusLabel).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={role} onValueChange={setRole}>
          <SelectTrigger className="w-full sm:w-52" aria-label="Filter agents by role">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All roles</SelectItem>
            {roles.map((item) => (
              <SelectItem key={item} value={item}>
                {item}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus />
          Create Agent
        </Button>
      </div>
      <Card className="mt-4 overflow-hidden shadow-none">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-52">Agent</TableHead>
              <TableHead className="min-w-48">Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="min-w-40">Model</TableHead>
              <TableHead>Budget/day</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map((agent) => (
              <TableRow key={agent.id}>
                <TableCell>
                  <div className="flex items-center gap-3">
                    <AgentAvatar name={agent.name} accent={agent.accent} size="sm" />
                    <span className="font-medium">{agent.name}</span>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">{agent.role}</TableCell>
                <TableCell>
                  <StatusBadge status={agent.status} />
                </TableCell>
                <TableCell className="font-mono text-xs">{agent.model}</TableCell>
                <TableCell className="font-mono">${agent.dailyBudget}</TableCell>
                <TableCell className="text-muted-foreground">
                  {agent.createdAt ?? "Today"}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon" asChild aria-label={`Edit ${agent.name}`}>
                      <Link to="/demo/agents/$agentId" params={{ agentId: agent.id }}>
                        <Pencil />
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => duplicate(agent)}
                      aria-label={`Duplicate ${agent.name}`}
                    >
                      <Copy />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setArchiveAgent(agent)}
                      aria-label={`Archive ${agent.name}`}
                    >
                      <Archive />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      {!visible.length && (
        <p className="py-12 text-center text-sm text-muted-foreground">
          No agents match these filters.
        </p>
      )}
      <CreateAgentWizard open={createOpen} onOpenChange={setCreateOpen} />
      <TypedConfirmDialog
        open={Boolean(archiveAgent)}
        onOpenChange={(open) => !open && setArchiveAgent(null)}
        title={`Archive ${archiveAgent?.name ?? "agent"}?`}
        description="This removes the agent from your active team. Its historical audit data remains available."
        keyword="ARCHIVE"
        action="Archive agent"
        onConfirm={() => {
          if (archiveAgent) {
            removeAgent(archiveAgent.id);
            toast.success(`${archiveAgent.name} archived`);
            setArchiveAgent(null);
          }
        }}
      />
    </div>
  );
}

function IntegrationsSettings() {
  return (
    <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {integrations.map(({ name, icon: Icon, connected, lastUsed }) => (
        <Card key={name} className="shadow-none">
          <CardHeader className="flex-row items-start gap-3 space-y-0">
            <span className="grid size-10 place-items-center rounded-md bg-muted">
              <Icon className="size-5" />
            </span>
            <div className="min-w-0 flex-1">
              <CardTitle className="text-sm">{name}</CardTitle>
              <Badge
                variant="outline"
                className={`mt-2 ${connected ? "border-success/30 bg-success/12 text-success" : "text-muted-foreground"}`}
              >
                {connected ? "Connected" : "Not connected"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <p className="mb-4 text-xs text-muted-foreground">Last used: {lastUsed}</p>
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => toast.info(`${name} configuration opened`)}
            >
              Configure
            </Button>
          </CardContent>
        </Card>
      ))}
      <button
        type="button"
        onClick={() => toast.info("Integration catalog opened")}
        className="grid min-h-48 place-items-center rounded-xl border border-dashed bg-card p-6 text-center transition-colors hover:bg-accent"
      >
        <span>
          <span className="mx-auto grid size-10 place-items-center rounded-full bg-muted">
            <Plus className="size-5" />
          </span>
          <span className="mt-3 block text-sm font-medium">Add integration</span>
          <span className="mt-1 block text-xs text-muted-foreground">Connect another service</span>
        </span>
      </button>
    </div>
  );
}

function SecuritySettings() {
  const { agents, daemonRunning, setDaemonRunning, setKillSwitchOpen, logSystemEvent } = useStore();
  const [deleteDialog, setDeleteDialog] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState(0);

  const exportAll = () => {
    if (exporting) return;
    setExporting(true);
    setExportProgress(8);
    const timer = window.setInterval(() => {
      setExportProgress((value) => {
        if (value >= 100) return value;
        const next = Math.min(100, value + 12);
        if (next >= 100) {
          window.clearInterval(timer);
          const zip = createZip([
            { name: "agents.json", content: JSON.stringify(agents, null, 2) },
            {
              name: "README.txt",
              content: "Eeze Agents workspace export\nGenerated in-app from mock data.",
            },
          ]);
          downloadBlob(zip, `eeze-agents-export-${Date.now()}.zip`);
          toast.success("Export ready — eeze-agents-export.zip downloaded");
          logSystemEvent({
            label: "Workspace data exported",
            detail: "Full export archive downloaded.",
            severity: "info",
          });
          window.setTimeout(() => {
            setExporting(false);
            setExportProgress(0);
          }, 600);
        }
        return next;
      });
    }, 220);
  };

  return (
    <div className="mt-5 grid gap-5 lg:grid-cols-[1.1fr_.9fr]">
      <div className="space-y-5">
        <Card className="border-destructive/35 shadow-none">
          <CardHeader className="flex-col items-start gap-4 space-y-0 sm:flex-row sm:items-center">
            <span className="grid size-11 place-items-center rounded-md bg-destructive/12 text-destructive">
              <ShieldAlert />
            </span>
            <div className="flex-1">
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="size-4 text-destructive" />
                Emergency kill switch
              </CardTitle>
              <CardDescription>
                Immediately terminate every agent and stop the cua-driver daemon.
              </CardDescription>
            </div>
            <Button variant="destructive" onClick={() => setKillSwitchOpen(true)}>
              <OctagonX />
              Stop all agents
            </Button>
          </CardHeader>
          <CardContent className="flex items-center gap-4 border-t pt-5">
            <div className="min-w-0 flex-1">
              <Label htmlFor="kill-switch-armed">Agents armed</Label>
              <p className="mt-1 text-sm text-muted-foreground">
                {daemonRunning
                  ? "Agents may execute actions. Disabling requires typing STOP."
                  : "Kill switch active — all execution is halted."}
              </p>
            </div>
            <Switch
              id="kill-switch-armed"
              checked={daemonRunning}
              onCheckedChange={(checked) => {
                if (!checked) {
                  setKillSwitchOpen(true);
                  return;
                }
                setDaemonRunning(true);
                logSystemEvent({
                  label: "Agents re-armed",
                  detail: "Kill switch released; daemon restarted.",
                  severity: "info",
                });
                toast.success("Agents re-armed");
              }}
            />
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>Data redaction</CardTitle>
            <CardDescription>
              Remove sensitive values from screenshots and audit logs.
            </CardDescription>
          </CardHeader>
          <CardContent className="divide-y">
            {redactionOptions.map((option) => (
              <ToggleRow key={option.id} {...option} />
            ))}
          </CardContent>
        </Card>
      </div>
      <div className="space-y-5">
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>Audit log retention</CardTitle>
            <CardDescription>
              Choose how long run details and screenshots are retained.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Label htmlFor="retention">Retention period</Label>
            <Select defaultValue="90">
              <SelectTrigger id="retention" className="mt-2 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="30">30 days</SelectItem>
                <SelectItem value="90">90 days</SelectItem>
                <SelectItem value="365">1 year</SelectItem>
                <SelectItem value="forever">Forever</SelectItem>
              </SelectContent>
            </Select>
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>Data controls</CardTitle>
            <CardDescription>Export or permanently remove workspace data.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <Button variant="outline" disabled={exporting} onClick={exportAll}>
              <Braces />
              {exporting ? "Preparing export…" : "Export all data"}
            </Button>
            {exporting && (
              <div>
                <Progress value={exportProgress} className="mt-1" />
                <p className="mt-2 font-mono text-xs text-muted-foreground">
                  {exportProgress}% · building .zip archive
                </p>
              </div>
            )}
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              onClick={() => setDeleteDialog(true)}
            >
              <AlertTriangle />
              Delete all data
            </Button>
          </CardContent>
        </Card>
      </div>
      <TypedConfirmDialog
        open={deleteDialog}
        onOpenChange={setDeleteDialog}
        title="Delete all workspace data?"
        description="This irreversible action removes agents, memories, run history, and audit logs."
        keyword="DELETE"
        action="Delete all data"
        onConfirm={() => {
          setDeleteDialog(false);
          toast.success("Deletion request recorded");
          logSystemEvent({
            label: "Workspace deletion requested",
            detail: "All workspace data scheduled for removal.",
            severity: "critical",
          });
        }}
      />
    </div>
  );
}

function BillingSettings() {
  const { agents } = useStore();
  return (
    <div className="mt-5 space-y-5">
      <div className="grid gap-5 lg:grid-cols-[.8fr_1.2fr]">
        <Card className="shadow-none">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardDescription>Current plan</CardDescription>
                <CardTitle className="mt-1 text-2xl">Pro</CardTitle>
              </div>
              <Badge>Active</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex justify-between text-sm">
              <span>6,420 of 10,000 tasks</span>
              <span className="font-mono">64%</span>
            </div>
            <Progress value={64} className="mt-3" />
            <p className="mt-3 text-xs text-muted-foreground">Resets October 1, 2026</p>
            <Button className="mt-5 w-full" onClick={() => toast.info("Plan options opened")}>
              <Sparkles />
              Upgrade plan
            </Button>
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>Monthly spend</CardTitle>
            <CardDescription>Agent costs over the last six months.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex h-48 items-end gap-3 border-b pb-2">
              {spend.map((item) => (
                <div
                  key={item.month}
                  className="flex h-full flex-1 flex-col justify-end gap-2 text-center"
                >
                  <span className="font-mono text-[10px] text-muted-foreground">
                    ${item.amount}
                  </span>
                  <div
                    className="min-h-1 rounded-t-sm bg-info"
                    style={{ height: `${item.amount}%` }}
                  />
                  <span className="text-xs text-muted-foreground">{item.month}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>Usage by agent</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead>Tasks this month</TableHead>
                <TableHead>Cost</TableHead>
                <TableHead className="min-w-40">Budget used</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.map((agent, index) => {
                const percentage = [74, 58, 39][index] ?? 12;
                return (
                  <TableRow key={agent.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <AgentAvatar name={agent.name} accent={agent.accent} size="sm" />
                        <span className="font-medium">{agent.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>{[428, 816, 132][index] ?? 0}</TableCell>
                    <TableCell className="font-mono">
                      ${[22.18, 14.92, 8.44][index]?.toFixed(2) ?? "0.00"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Progress value={percentage} className="w-24" />
                        <span className="font-mono text-xs">{percentage}%</span>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card className="shadow-none">
        <CardHeader className="sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Payment method</CardTitle>
            <CardDescription className="mt-1">Visa ending in 4242 · expires 09/28</CardDescription>
          </div>
          <Button variant="outline" onClick={() => toast.info("Payment method editor opened")}>
            <WalletCards />
            Update payment method
          </Button>
        </CardHeader>
      </Card>
    </div>
  );
}

function SystemSettings() {
  const { agents, daemonRunning, setDaemonRunning, systemEvents, logSystemEvent } = useStore();
  const statusResult = useQuery(systemStatusQuery());
  const live = statusResult.data;
  const daemonRaw = live?.daemon;
  const daemonObject = typeof daemonRaw === "object" && daemonRaw !== null ? daemonRaw : null;
  const daemonText = typeof daemonRaw === "string" ? daemonRaw : (live?.daemon_status ?? "");
  const daemonOk = live
    ? daemonObject
      ? Boolean(daemonObject.running)
      : ["running", "healthy", "ok", "up"].includes(daemonText.toLowerCase())
    : daemonRunning;
  const jevRaw = live?.jev;
  const jevObject = typeof jevRaw === "object" && jevRaw !== null ? jevRaw : null;
  const jevVersion = jevObject?.model ?? (typeof jevRaw === "string" ? jevRaw : "v2.7.1");
  const jevStatus = jevObject
    ? `${jevObject.calls ?? 0} calls · $${(jevObject.cost_usd ?? 0).toFixed(3)}`
    : (live?.jev_status ?? "API online");
  const agentsCount = live?.agents?.length ?? live?.agents_count ?? agents.length;
  const driverDetail = daemonObject?.pid
    ? `PID ${daemonObject.pid} · ${daemonObject.permission_mode ?? "standard"}`
    : (live?.version ?? "v0.18.4");
  const services: Array<[string, string, string, boolean]> = [
    ["cua-driver", driverDetail, daemonOk ? "Running" : "Stopped", daemonOk],
    ["Jev", jevVersion, jevStatus, true],
    ["Daemon", daemonOk ? "Healthy" : "Terminated", daemonOk ? "Running" : "Stopped", daemonOk],
    [
      "Agents",
      `${agentsCount} registered · ${live?.runs_total ?? 0} runs`,
      statusResult.isError ? "Offline data" : "Live",
      !statusResult.isError,
    ],
  ];
  const restart = (name: string) => {
    setDaemonRunning(true);
    logSystemEvent({
      label: `${name} restarted`,
      detail: `${name} process restarted from Settings.`,
      severity: "info",
    });
    toast.success(`${name} restart requested`);
  };
  return (
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <Card className="shadow-none">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle>Runtime health</CardTitle>
              <CardDescription>
                Local services that power background automation. Polled every 10s.
              </CardDescription>
            </div>
            <RefreshButton
              onRefresh={() => void statusResult.refetch()}
              refreshing={statusResult.isFetching}
            />
          </div>
        </CardHeader>
        <CardContent className="divide-y">
          {services.map(([name, version, status, ok]) => (
            <div key={name} className="flex items-center gap-3 py-4 first:pt-0 last:pb-0">
              <span
                className={`grid size-9 place-items-center rounded-md ${ok ? "bg-success/12 text-success" : "bg-destructive/12 text-destructive"}`}
              >
                <Gauge className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-medium">{name}</p>
                <p className="font-mono text-xs text-muted-foreground">{version}</p>
              </div>
              <Badge
                variant="outline"
                className={
                  ok
                    ? "border-success/30 bg-success/12 text-success"
                    : "border-destructive/30 bg-destructive/12 text-destructive"
                }
              >
                <span className="size-1.5 rounded-full bg-current" />
                {status}
              </Badge>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>Controls</CardTitle>
          <CardDescription>Restart local processes or increase diagnostic detail.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-2 sm:grid-cols-2">
            <Button variant="outline" onClick={() => restart("Driver")}>
              <RefreshCw />
              Restart driver
            </Button>
            <Button variant="outline" onClick={() => restart("Daemon")}>
              <RefreshCw />
              Restart daemon
            </Button>
          </div>
          <div>
            <Label htmlFor="log-level">Log level</Label>
            <Select defaultValue="info">
              <SelectTrigger id="log-level" className="mt-2 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="info">Info</SelectItem>
                <SelectItem value="debug">Debug</SelectItem>
                <SelectItem value="trace">Trace</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="rounded-md border bg-muted/40 p-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <KeyRound className="size-4" />
              Local API
            </div>
            <p className="mt-2 font-mono text-xs text-muted-foreground">
              {API_URL} · {statusResult.isError ? "unreachable" : "connected"}
            </p>
          </div>
        </CardContent>
      </Card>
      <Card className="shadow-none lg:col-span-2">
        <CardHeader>
          <CardTitle>System event log</CardTitle>
          <CardDescription>
            Emergency stops, restarts, and data actions recorded this session.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {systemEvents.length ? (
            <ul className="divide-y">
              {systemEvents.map((event) => (
                <li key={event.id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                  <span
                    className={`mt-0.5 grid size-8 shrink-0 place-items-center rounded-md ${event.severity === "critical" ? "bg-destructive/12 text-destructive" : "bg-muted text-muted-foreground"}`}
                  >
                    {event.severity === "critical" ? (
                      <AlertTriangle className="size-4" />
                    ) : (
                      <Gauge className="size-4" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{event.label}</p>
                    <p className="text-sm text-muted-foreground">{event.detail}</p>
                  </div>
                  <span className="font-mono text-xs text-muted-foreground">{event.timestamp}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No system events recorded yet.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ToggleRow({
  id,
  label,
  detail,
  defaultChecked,
}: {
  id: string;
  label: string;
  detail: string;
  defaultChecked: boolean;
}) {
  return (
    <div className="flex items-center gap-4 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <Label htmlFor={id}>{label}</Label>
        <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
      </div>
      <Switch id={id} defaultChecked={defaultChecked} />
    </div>
  );
}

function LiveSettings() {
  const queryClient = useQueryClient();
  const info = useQuery(systemInfoQuery());
  const status = useQuery(systemStatusQuery());
  const setup = useQuery(setupStateQuery());
  const notify = useMutation({
    mutationFn: (enabled: boolean) => api.setNotify(enabled),
    onSuccess: async (result) => {
      toast.success(result.enabled ? "Approval alerts on." : "Approval alerts off.");
      await queryClient.invalidateQueries({ queryKey: ["system-status"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const notifyRoutines = useMutation({
    mutationFn: (enabled: boolean) => api.setNotifyRoutines(enabled),
    onSuccess: async (result) => {
      toast.success(result.enabled ? "Routine failure alerts on." : "Routine failure alerts off.");
      await queryClient.invalidateQueries({ queryKey: ["system-status"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const daemon = typeof info.data?.daemon === "object" ? info.data?.daemon : undefined;
  const keys: [string, string][] = [
    ["typesafe", "Typesafe — Jev judgment brain"],
    ["extract", "Invoice extraction"],
    ["imap", "Mailbox app password"],
  ];
  const paths: [string, string | undefined][] = [
    ["Agent store", info.data?.store_path],
    ["Local write token", info.data?.token_path],
    ["User agents", info.data?.user_agents_path],
    ["Repo agents", info.data?.repo_agents_path],
    ["Artifacts", info.data?.artifacts_path],
  ];

  if (info.isError)
    return (
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
        <ErrorState onRetry={() => void info.refetch()} />
      </div>
    );

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Local runtime, mailbox and keys. Everything stays on this machine.
      </p>

      <Card className="mt-6">
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold">Approval notifications</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                A Windows alert when a run pauses for approval — without stealing focus.
              </p>
            </div>
            <Switch
              checked={status.data?.notifications_enabled ?? true}
              disabled={!status.data || notify.isPending}
              aria-label="Desktop alerts for approvals"
              onCheckedChange={(checked) => notify.mutate(checked)}
            />
          </div>
          <div className="mt-5 flex items-start justify-between gap-4 border-t pt-5">
            <div>
              <h2 className="text-base font-semibold">Routine failure notifications</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Alert on new routine failures only. Off by default; past failures are not replayed.
              </p>
            </div>
            <Switch
              checked={status.data?.routine_failure_notifications_enabled ?? false}
              disabled={!status.data || notifyRoutines.isPending}
              aria-label="Desktop alerts for routine failures"
              onCheckedChange={(checked) => notifyRoutines.mutate(checked)}
            />
          </div>
        </CardHeader>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <h2 className="text-base font-semibold">Runtime</h2>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs uppercase text-muted-foreground">Control plane</dt>
              <dd className="mt-1">running · pid {info.data?.api_pid ?? "?"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-muted-foreground">Hands (cua-driver)</dt>
              <dd className="mt-1">
                {daemon?.running ? `running · pid ${daemon.pid ?? "?"}` : "stopped"}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-muted-foreground">Version</dt>
              <dd className="mt-1">{info.data?.version ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-muted-foreground">Python</dt>
              <dd className="mt-1">{info.data?.python ?? "—"}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs uppercase text-muted-foreground">Runsets · backups</dt>
              <dd className="mt-1">
                {info.data?.runsets ?? 0} · {info.data?.backups ?? 0}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <ProvidersCard />

      <Card className="mt-4">
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-base font-semibold">Mailbox</h2>
            <Button variant="outline" size="sm" asChild>
              <Link to="/setup">Open setup wizard</Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent className="text-sm">
          {setup.data?.imap_configured ? (
            <p>
              Connected as <span className="font-medium">{setup.data.imap_user}</span>
              {setup.data.imap_host ? ` (${setup.data.imap_host})` : ""} — read-only, pulls on
              demand.
            </p>
          ) : (
            <p className="text-muted-foreground">
              No mailbox configured yet — connect one in the setup wizard.
            </p>
          )}
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <h2 className="text-base font-semibold">Other keys</h2>
          <CardDescription>
            Presence only — values live in the repo .env and never reach this page. Model provider
            keys are above.
          </CardDescription>
        </CardHeader>
        <CardContent className="divide-y rounded-md border p-0">
          {keys.map(([id, label]) => (
            <div key={id} className="flex items-center justify-between px-4 py-3 text-sm">
              <span>{label}</span>
              {info.data?.keys?.[id] ? (
                <Badge variant="secondary" className="font-normal">
                  Configured
                </Badge>
              ) : (
                <Badge variant="outline" className="font-normal text-muted-foreground">
                  Not set
                </Badge>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <h2 className="text-base font-semibold">Paths &amp; data</h2>
          <CardDescription>
            Audit trail lives in the store; runs and screenshots under artifacts; backups (including
            the .env) are git-ignored and never leave the machine.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {paths.map(([label, value]) => (
            <div key={label} className="flex flex-col gap-0.5 sm:flex-row sm:items-center sm:gap-3">
              <span className="w-40 shrink-0 text-xs uppercase text-muted-foreground">{label}</span>
              <code className="break-all font-mono text-xs">{value ?? "—"}</code>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
