import { useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  CardSkeletonGrid,
  ErrorState,
  OfflineNotice,
  RefreshButton,
} from "@/components/data-state";
import { agentsQuery } from "@/lib/queries";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AgentAvatar } from "@/components/agent-avatar";
import { StatusBadge } from "@/components/status-badge";
import { useStore } from "@/components/app-store";
import { statusLabel, type AgentStatus } from "@/lib/mock-data";
import { CreateAgentWizard } from "@/components/create-agent-wizard";
import { DEMO_MODE, api } from "@/lib/api";

export const Route = createFileRoute("/demo/")({
  head: () => ({
    meta: [
      { title: "Team Dashboard — Eeze Agents" },
      {
        name: "description",
        content:
          "Watch your AI agent team work in the background: live status, today's tasks, success rate and spend.",
      },
      { property: "og:title", content: "Team Dashboard — Eeze Agents" },
      {
        property: "og:description",
        content: "Manage a team of AI agents that automate work on your computer, quietly.",
      },
    ],
  }),
  component: Dashboard,
});

const statuses: (AgentStatus | "all")[] = ["all", "working", "needs_approval", "idle", "error"];

function Dashboard() {
  const queryClient = useQueryClient();
  const removeAgent = useMutation({
    mutationFn: (id: string) => api.removeAgent(id),
    onSuccess: async () => {
      toast.success("Agent removed.");
      await queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const { agents: localAgents, setCommandOpen } = useStore();
  const [filter, setFilter] = useState<AgentStatus | "all">("all");
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const agentsResult = useQuery(agentsQuery());
  const offline = agentsResult.isError;
  const agents = agentsResult.data ?? localAgents;

  const visible = useMemo(
    () =>
      agents.filter(
        (a) =>
          (filter === "all" || a.status === filter) &&
          (a.name + a.role).toLowerCase().includes(query.trim().toLowerCase()),
      ),
    [agents, filter, query],
  );

  const totals = useMemo(
    () => ({
      tasks: agents.reduce((n, a) => n + a.metrics.tasksToday, 0),
      cost: agents.reduce((n, a) => n + a.metrics.costToday, 0),
    }),
    [agents],
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 pb-24 sm:px-6 sm:py-10 md:pb-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Your team</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {agents.length} agents · {totals.tasks} tasks today · ${totals.cost.toFixed(2)} spent
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RefreshButton
            onRefresh={() => void agentsResult.refetch()}
            refreshing={agentsResult.isFetching}
          />
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" />
            Create Agent
          </Button>
        </div>
      </div>
      {offline && <OfflineNotice />}

      <div className="mt-6 flex flex-wrap items-center gap-2">
        <div className="relative hidden min-w-64 flex-1 md:block">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setCommandOpen(true)}
            aria-label="Command bar"
            placeholder="Ask anything, or @mention an agent…"
            className="pl-9"
          />
        </div>
        <Select value={filter} onValueChange={(v) => setFilter(v as AgentStatus | "all")}>
          <SelectTrigger className="w-full sm:w-44" aria-label="Filter by status">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            {statuses.map((s) => (
              <SelectItem key={s} value={s}>
                {s === "all" ? "All statuses" : statusLabel[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {offline && (
        <ErrorState
          detail="Showing sample data so the design stays reviewable."
          onRetry={() => void agentsResult.refetch()}
        />
      )}

      {agentsResult.isPending ? (
        <CardSkeletonGrid />
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((agent) => (
            <Card key={agent.id} className="transition-shadow hover:shadow-sm">
              <CardHeader className="flex flex-row items-start gap-3 space-y-0">
                <AgentAvatar name={agent.name} accent={agent.accent} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="truncate text-base font-semibold tracking-tight">
                      {agent.name}
                    </h2>
                    <StatusBadge status={agent.status} />
                  </div>
                  <p className="truncate text-sm text-muted-foreground">{agent.role}</p>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="line-clamp-2 min-h-10 rounded-md bg-muted/60 px-3 py-2 text-sm text-muted-foreground">
                  {agent.currentTask ?? "No active task"}
                </p>
                <dl className="grid grid-cols-3 gap-2 text-center">
                  <Metric label="Tasks" value={String(agent.metrics.tasksToday)} />
                  <Metric
                    label="Success"
                    value={
                      agent.metrics.successRate !== null
                        ? `${Math.round(agent.metrics.successRate * 100)}%`
                        : "—"
                    }
                  />
                  <Metric
                    label="Cost"
                    value={`$${agent.metrics.costToday.toFixed(agent.metrics.costToday < 0.01 && agent.metrics.costToday > 0 ? 4 : 2)}`}
                  />
                </dl>
              </CardContent>
              <CardFooter className="gap-2">
                <Button variant="secondary" className="flex-1" asChild>
                  <Link to="/demo/agents/$agentId" params={{ agentId: agent.id }}>
                    Open {agent.name}
                  </Link>
                </Button>
                {!DEMO_MODE && agent.source === "user" && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove ${agent.name}`}
                    disabled={removeAgent.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Remove agent "${agent.name}"? Runs stay in the audit trail.`,
                        )
                      ) {
                        removeAgent.mutate(agent.id);
                      }
                    }}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {!agentsResult.isPending && visible.length === 0 && (
        <p className="mt-16 text-center text-sm text-muted-foreground">
          No agents match this filter.
        </p>
      )}
      <CreateAgentWizard open={createOpen} onOpenChange={setCreateOpen} />
      <Button
        size="icon"
        className="fixed bottom-5 right-5 z-30 size-12 rounded-full shadow-lg md:hidden"
        onClick={() => setCommandOpen(true)}
        aria-label="Open command bar"
      >
        <Search className="size-5" />
      </Button>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border py-2">
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-sm font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
