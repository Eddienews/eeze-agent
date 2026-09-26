import { useState } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  ArrowLeft,
  Clock3,
  Edit3,
  Eye,
  Pause,
  Play,
  PlayCircle,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState, RefreshButton, RowSkeleton } from "@/components/data-state";
import { agentQuery, routinesQuery, runsQuery } from "@/lib/queries";
import { DEMO_MODE } from "@/lib/api";
import { CreateAgentWizard } from "@/components/create-agent-wizard";
import { getAgent } from "@/lib/mock-data";

export const Route = createFileRoute("/demo/agents/$agentId")({
  loader: ({ params }) => {
    const agent = getAgent(params.agentId);
    return agent ? { name: agent.name, role: agent.role } : { name: "Agent", role: "Eeze Agents" };
  },
  head: ({ loaderData }) => {
    const title = loaderData
      ? `${loaderData.name} — ${loaderData.role} · Eeze Agents`
      : "Agent unavailable — Eeze Agents";
    const description = loaderData
      ? `Manage routines, memory, permissions, history and settings for ${loaderData.name}.`
      : "The requested agent is unavailable.";
    return {
      meta: [
        { title },
        { name: "description", content: description },
        { property: "og:title", content: title },
        { property: "og:description", content: description },
        { property: "og:type", content: "website" },
        { name: "twitter:card", content: "summary" },
        ...(!loaderData ? [{ name: "robots", content: "noindex" }] : []),
      ],
    };
  },
  component: AgentDetail,
});

function AgentDetail() {
  const { agentId } = Route.useParams();
  const navigate = useNavigate({ from: "/demo/agents/$agentId" });
  const { agents, updateAgent, toggleRoutine } = useStore();
  const agentResult = useQuery(agentQuery(agentId));
  const runsResult = useQuery(runsQuery({ agent_id: agentId }));
  const local = agents.find((item) => item.id === agentId);
  const base = local ?? agentResult.data;
  const agent =
    base && agentResult.data
      ? {
          ...base,
          ...agentResult.data,
          ...(DEMO_MODE ? { routines: base.routines, memory: base.memory } : {}),
        }
      : base;
  const [name, setName] = useState(local?.name ?? "");
  const [editingMemory, setEditingMemory] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  if (agentResult.isPending && !agent)
    return (
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <Skeleton className="h-24 w-full rounded-xl" />
        <RowSkeleton rows={3} />
      </div>
    );
  if (!agent)
    return (
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <ErrorState
          message="We couldn't load this agent."
          onRetry={() => void agentResult.refetch()}
        />
      </div>
    );
  const history = runsResult.data ?? agent.history;
  const paused = agent.status === "idle";

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <Button variant="ghost" size="sm" asChild className="-ml-2 mb-5 text-muted-foreground">
        <Link to="/demo">
          <ArrowLeft />
          Team
        </Link>
      </Button>

      <header className="flex flex-col gap-6 border-b pb-8">
        <div className="flex flex-wrap items-center gap-4">
          <AgentAvatar
            name={agent.name}
            accent={agent.accent}
            size="lg"
            className="size-20 text-2xl"
          />
          <div className="min-w-56 flex-1">
            <Input
              value={name}
              aria-label="Agent name"
              onChange={(event) => setName(event.target.value)}
              onBlur={() => name.trim() && updateAgent(agent.id, { name: name.trim() })}
              className="h-10 max-w-md border-transparent bg-transparent px-0 text-2xl font-semibold shadow-none focus-visible:border-input focus-visible:px-2"
            />
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p className="text-sm text-muted-foreground">{agent.role}</p>
              <StatusBadge status={agent.status} />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <RefreshButton
              onRefresh={() => {
                void agentResult.refetch();
                void runsResult.refetch();
              }}
              refreshing={agentResult.isFetching || runsResult.isFetching}
            />
            {history[0] && (
              <Button variant="outline" asChild>
                <Link
                  to="/demo/agents/$agentId/runs/$runId"
                  params={{ agentId: agent.id, runId: history[0]!.id }}
                >
                  <Eye />
                  View Run
                </Link>
              </Button>
            )}
            {!DEMO_MODE && (
              <Button variant="outline" onClick={() => setEditOpen(true)}>
                <Edit3 />
                Edit
              </Button>
            )}
            {DEMO_MODE && (
              <Button
                variant={paused ? "default" : "outline"}
                onClick={() => {
                  updateAgent(agent.id, { status: paused ? "working" : "idle" });
                  toast.success(paused ? `${agent.name} resumed` : `${agent.name} paused`);
                }}
              >
                {paused ? <Play /> : <Pause />}
                {paused ? "Resume" : "Pause"}
              </Button>
            )}
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border sm:grid-cols-4">
          <TopMetric label="Tasks today" value={String(agent.metrics.tasksToday)} />
          <TopMetric
            label="Success rate"
            value={
              agent.metrics.successRate !== null
                ? `${Math.round(agent.metrics.successRate * 100)}%`
                : "—"
            }
          />
          <TopMetric
            label="Cost"
            value={`$${agent.metrics.costToday.toFixed(agent.metrics.costToday < 0.01 && agent.metrics.costToday > 0 ? 4 : 2)}`}
          />
          {DEMO_MODE ? (
            <TopMetric label="Time saved" value={agent.metrics.timeSaved ?? "—"} />
          ) : (
            <TopMetric label="Runs" value={String(agent.metrics.runsTotal ?? 0)} />
          )}
        </dl>
      </header>

      <Tabs defaultValue="overview" className="mt-7">
        <TabsList className="h-auto w-full justify-start overflow-x-auto bg-transparent p-0">
          {["overview", "routines", "memory", "history", "settings"].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="rounded-none border-b-2 border-transparent px-4 py-2 capitalize data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview" className="mt-6 space-y-4">
          <div className="grid gap-4 lg:grid-cols-[1.1fr_.9fr]">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Agent profile</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <div>
                  <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">Role</p>
                  <p className="text-sm leading-6">
                    {agent.description ??
                      "No description yet — add one in agents.yaml (user agents)."}
                  </p>
                </div>
                {agent.personality && (
                  <div>
                    <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">
                      Personality
                    </p>
                    <p className="text-sm leading-6">{agent.personality}</p>
                  </div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Performance</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3">
                {DEMO_MODE ? (
                  <>
                    <DetailMetric label="Completed" value="38 this week" />
                    <DetailMetric label="Avg. duration" value="3m 14s" />
                    <DetailMetric label="Approval rate" value="91%" />
                    <DetailMetric label="Steps" value="412 today" />
                  </>
                ) : (
                  <>
                    <DetailMetric label="Runs total" value={String(agent.metrics.runsTotal ?? 0)} />
                    <DetailMetric label="Last 24h" value={String(agent.metrics.tasksToday)} />
                    <DetailMetric
                      label="Success rate"
                      value={
                        agent.metrics.successRate !== null
                          ? `${Math.round(agent.metrics.successRate * 100)}%`
                          : "—"
                      }
                    />
                    <DetailMetric
                      label="Avg. cycle"
                      value={
                        agent.metrics.avgCycleMs != null
                          ? `${(agent.metrics.avgCycleMs / 1000).toFixed(1)}s`
                          : "—"
                      }
                    />
                  </>
                )}
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-[1.1fr_.9fr]">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Permissions</CardTitle>
              </CardHeader>
              <CardContent className="divide-y rounded-md border p-0">
                {agent.permissions.map((permission) => (
                  <Label
                    key={permission.id}
                    htmlFor={`perm-${permission.id}`}
                    className={`flex items-center gap-3 p-4 font-normal ${DEMO_MODE ? "cursor-pointer" : ""}`}
                  >
                    {DEMO_MODE ? (
                      <Checkbox
                        id={`perm-${permission.id}`}
                        checked={permission.granted}
                        onCheckedChange={(checked) =>
                          updateAgent(agent.id, {
                            permissions: agent.permissions.map((item) =>
                              item.id === permission.id
                                ? { ...item, granted: checked === true }
                                : item,
                            ),
                          })
                        }
                      />
                    ) : (
                      <ShieldCheck className="size-4 text-primary" />
                    )}
                    <span>{permission.label}</span>
                  </Label>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Connected tools</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {agent.tools.map((tool) => (
                  <Badge key={tool} variant="secondary" className="font-normal">
                    {tool}
                  </Badge>
                ))}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="routines" className="mt-6 space-y-3">
          {!DEMO_MODE && <AgentRoutines agentId={agent.id} />}
          {DEMO_MODE &&
            agent.routines.map((routine) => (
              <div
                key={routine.id}
                className="flex flex-col gap-4 rounded-md border bg-card p-4 sm:flex-row sm:items-center"
              >
                <Switch
                  checked={routine.enabled}
                  aria-label={`Toggle ${routine.name}`}
                  onCheckedChange={() => toggleRoutine(agent.id, routine.id)}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{routine.name}</p>
                  <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Clock3 className="size-3.5" />
                    {routine.schedule}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => toast.success(`${routine.name} started`)}
                  >
                    <PlayCircle />
                    Run now
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => toast.info(`Editing ${routine.name}`)}
                  >
                    <Edit3 />
                    Edit
                  </Button>
                </div>
              </div>
            ))}
        </TabsContent>

        <TabsContent value="memory" className="mt-6 grid gap-3 sm:grid-cols-2">
          {!DEMO_MODE && (
            <Card className="sm:col-span-2">
              <CardHeader>
                <CardTitle className="text-base">Agent memory</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <p className="text-sm leading-6 text-muted-foreground">
                  Per-agent memory is not implemented yet (v2 roadmap). Every run is reconstructible
                  in the audit trail instead — judgments, verifications and approvals live in each
                  runset's journal.
                </p>
                <Button variant="outline" size="sm" asChild>
                  <Link to="/demo/agents/$agentId" params={{ agentId: agent.id }}>
                    See the History tab
                  </Link>
                </Button>
              </CardContent>
            </Card>
          )}
          {DEMO_MODE &&
            agent.memory.map((memory) => (
              <Card key={memory.id}>
                <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
                  <div>
                    <CardTitle className="text-sm">{memory.title}</CardTitle>
                    <p className="mt-1 text-xs text-muted-foreground">Learned {memory.learnedAt}</p>
                  </div>
                  <div className="flex">
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`Edit ${memory.title}`}
                      onClick={() =>
                        setEditingMemory(editingMemory === memory.id ? null : memory.id)
                      }
                    >
                      <Edit3 />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`Delete ${memory.title}`}
                      onClick={() => {
                        updateAgent(agent.id, {
                          memory: agent.memory.filter((item) => item.id !== memory.id),
                        });
                        toast.success("Memory removed");
                      }}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  {editingMemory === memory.id ? (
                    <Textarea
                      autoFocus
                      defaultValue={memory.content}
                      className="min-h-24 resize-none"
                      onBlur={(event) => {
                        updateAgent(agent.id, {
                          memory: agent.memory.map((item) =>
                            item.id === memory.id ? { ...item, content: event.target.value } : item,
                          ),
                        });
                        setEditingMemory(null);
                        toast.success("Memory updated");
                      }}
                    />
                  ) : (
                    <p className="text-sm leading-6 text-muted-foreground">{memory.content}</p>
                  )}
                </CardContent>
              </Card>
            ))}
        </TabsContent>

        <TabsContent value="history" className="mt-6">
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Task</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Duration</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.map((run) => (
                    <TableRow
                      key={run.id}
                      tabIndex={0}
                      role="link"
                      className="cursor-pointer"
                      onClick={() =>
                        void navigate({
                          to: "/demo/agents/$agentId/runs/$runId",
                          params: { agentId: agent.id, runId: run.id },
                        })
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter")
                          void navigate({
                            to: "/demo/agents/$agentId/runs/$runId",
                            params: { agentId: agent.id, runId: run.id },
                          });
                      }}
                    >
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {run.startedAt}
                      </TableCell>
                      <TableCell className="min-w-56 font-medium">{run.task}</TableCell>
                      <TableCell>
                        <Outcome outcome={run.outcome} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{run.duration}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        ${run.cost.toFixed(2)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="settings" className="mt-6">
          {!DEMO_MODE && (
            <Card className="mb-4">
              <CardHeader>
                <CardTitle className="text-base">Agent settings</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm leading-6 text-muted-foreground">
                  Name, role, description, permissions (risk classes) and the tactical brain live in
                  ~/.eeze/agents.yaml — edit them from here.
                </p>
                <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                  <Edit3 />
                  Edit {agent.name}
                </Button>
              </CardContent>
            </Card>
          )}
          {DEMO_MODE && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Models, budget & autonomy</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-7 lg:grid-cols-2">
                <SettingSelect
                  label="Jev model"
                  value={agent.model}
                  options={["claude-sonnet-4.6", "gpt-5.2-mini", "gemini-3-pro"]}
                  onChange={(value) => updateAgent(agent.id, { model: value })}
                />
                <SettingSelect
                  label="Planner model"
                  value={agent.plannerModel}
                  options={["jev-planner-2", "jev-planner-fast", "jev-planner-deep"]}
                  onChange={(value) => updateAgent(agent.id, { plannerModel: value })}
                />
                <div className="space-y-3">
                  <Label htmlFor="budget">Maximum daily budget · ${agent.dailyBudget}</Label>
                  <Slider
                    id="budget"
                    value={[agent.dailyBudget]}
                    min={1}
                    max={50}
                    step={1}
                    onValueChange={(value) => updateAgent(agent.id, { dailyBudget: value[0] ?? 1 })}
                  />
                </div>
                <SettingSelect
                  label="Autonomy level"
                  value={agent.autonomy}
                  options={["suggest", "approve", "autonomous"]}
                  optionLabels={{
                    suggest: "Always ask",
                    approve: "Ask on risk",
                    autonomous: "Fully autonomous",
                  }}
                  onChange={(value) =>
                    updateAgent(agent.id, { autonomy: value as typeof agent.autonomy })
                  }
                />
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
      <CreateAgentWizard open={editOpen} onOpenChange={setEditOpen} editAgent={agent} />
    </div>
  );
}

function TopMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-card px-4 py-4">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/60 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-semibold tabular-nums">{value}</p>
    </div>
  );
}
function Outcome({ outcome }: { outcome: "running" | "success" | "failed" | "cancelled" }) {
  return (
    <Badge
      variant="outline"
      className={
        outcome === "running"
          ? "border-info/30 bg-info/12 text-info"
          : outcome === "success"
            ? "border-success/30 bg-success/12 text-success"
            : outcome === "failed"
              ? "border-destructive/30 bg-destructive/12 text-destructive"
              : "text-muted-foreground"
      }
    >
      {outcome}
    </Badge>
  );
}
function SettingSelect({
  label,
  value,
  options,
  optionLabels,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  optionLabels?: Record<string, string>;
  onChange: (value: string) => void;
}) {
  const id = label.toLowerCase().replaceAll(" ", "-");
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {optionLabels?.[option] ?? option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function AgentRoutines({ agentId }: { agentId: string }) {
  const routinesResult = useQuery(routinesQuery());
  const mine = (routinesResult.data ?? []).filter((routine) => routine.agent_id === agentId);
  if (routinesResult.isPending) return <RowSkeleton rows={2} />;
  if (!mine.length)
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No routines for this agent yet —{" "}
          <Link to="/routines" className="underline">
            schedule one on the Routines page
          </Link>
          .
        </CardContent>
      </Card>
    );
  return (
    <>
      {mine.map((routine) => (
        <div
          key={routine.id}
          className="flex flex-col gap-4 rounded-md border bg-card p-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="min-w-0">
            <p className="text-sm font-medium">{routine.name}</p>
            <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
              <Clock3 className="size-3.5" />
              {routine.kind}
              {routine.next_run_at
                ? ` · next ${new Date(routine.next_run_at).toLocaleString()}`
                : " · no next run"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={routine.enabled ? "secondary" : "outline"} className="font-normal">
              {routine.enabled ? "Enabled" : "Disabled"}
            </Badge>
            <Button size="sm" variant="outline" asChild>
              <Link to="/routines">Manage</Link>
            </Button>
          </div>
        </div>
      ))}
    </>
  );
}
