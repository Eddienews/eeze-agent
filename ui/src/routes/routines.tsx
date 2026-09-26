import { useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, History, Plus, Play, Trash2 } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ErrorState, RefreshButton, RowSkeleton } from "@/components/data-state";
import { agentsQuery, routineRunsQuery, routinesQuery } from "@/lib/queries";
import { DEMO_MODE, api, type ApiRoutine, type RoutineCreateRequest } from "@/lib/api";

export const Route = createFileRoute("/routines")({
  head: () => ({ meta: [{ title: "Routines — Eeze Agents" }] }),
  component: RoutinesPage,
});

const statusStyles: Record<string, string> = {
  ok: "bg-success/12 text-success border-success/25",
  done: "bg-success/12 text-success border-success/25",
  needs_approval: "bg-warning/15 text-warning border-warning/30",
  running: "bg-info/12 text-info border-info/25",
  spawned: "bg-info/12 text-info border-info/25",
  error: "bg-destructive/12 text-destructive border-destructive/30",
};

function statusLabel(status?: string | null) {
  if (!status) return "never ran";
  return status.replace(/_/g, " ");
}

function fmt(iso?: string | null) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scheduleLabel(routine: ApiRoutine) {
  const s = routine.schedule;
  if (s.type === "daily") return `Daily at ${s.at ?? "08:00"}`;
  if (s.type === "every") return `Every ${s.minutes ?? "?"} min`;
  return s.type;
}

function kindLabel(kind: string) {
  return kind === "invoices" ? "Invoices" : kind === "task" ? "Task" : kind;
}

/* ------------------------------- create panel ------------------------------ */

function CreateForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const agents = useQuery(agentsQuery());
  const [kind, setKind] = useState<"invoices" | "task">("invoices");
  const [id, setId] = useState("invoices-2");
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("default");
  const [schedType, setSchedType] = useState<"daily" | "every">("daily");
  const [at, setAt] = useState("08:00");
  const [minutes, setMinutes] = useState(60);
  const [search, setSearch] = useState("");
  const [emailSummary, setEmailSummary] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [taskPath, setTaskPath] = useState("");

  const create = useMutation({
    mutationFn: (body: RoutineCreateRequest) => api.createRoutine(body),
    onSuccess: async (routine) => {
      toast.success(`Routine "${routine.name}" saved — next run ${fmt(routine.next_run_at)}.`);
      await queryClient.invalidateQueries({ queryKey: ["routines"] });
      onDone();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const submit = () => {
    const body: RoutineCreateRequest = {
      id: id.trim(),
      ...(name.trim() ? { name: name.trim() } : {}),
      kind,
      agent_id: agentId,
      schedule:
        schedType === "daily"
          ? { type: "daily", at }
          : { type: "every", minutes: Number(minutes) || 60 },
      params:
        kind === "invoices"
          ? {
              ...(search.trim() ? { search: search.trim() } : {}),
              ...(emailSummary ? { email_summary: true } : {}),
              ...(emailTo.trim() ? { email_to: emailTo.trim() } : {}),
            }
          : { ...(taskPath.trim() ? { task_path: taskPath.trim() } : {}) },
    };
    create.mutate(body);
  };

  return (
    <Card className="mt-6">
      <CardContent className="grid gap-4 pt-6 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor="routine-id">ID (slug)</Label>
          <Input
            id="routine-id"
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="invoices"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="routine-name">Name</Label>
          <Input
            id="routine-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Gmail invoices"
          />
        </div>
        <div className="grid gap-1.5">
          <Label>Kind</Label>
          <div className="flex gap-2">
            <Button
              type="button"
              variant={kind === "invoices" ? "default" : "outline"}
              size="sm"
              onClick={() => setKind("invoices")}
            >
              Invoices
            </Button>
            <Button
              type="button"
              variant={kind === "task" ? "default" : "outline"}
              size="sm"
              onClick={() => setKind("task")}
            >
              Task (YAML)
            </Button>
          </div>
        </div>
        <div className="grid gap-1.5">
          <Label>Agent</Label>
          <div className="flex flex-wrap gap-2">
            {(agents.data ?? []).map((agent) => (
              <Button
                key={agent.id}
                type="button"
                variant={agentId === agent.id ? "default" : "outline"}
                size="sm"
                onClick={() => setAgentId(agent.id)}
              >
                {agent.name}
              </Button>
            ))}
            {!agents.data?.length && <span className="text-sm text-muted-foreground">default</span>}
          </div>
        </div>
        <div className="grid gap-1.5">
          <Label>Schedule</Label>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant={schedType === "daily" ? "default" : "outline"}
              size="sm"
              onClick={() => setSchedType("daily")}
            >
              Daily
            </Button>
            <Button
              type="button"
              variant={schedType === "every" ? "default" : "outline"}
              size="sm"
              onClick={() => setSchedType("every")}
            >
              Every…
            </Button>
            {schedType === "daily" ? (
              <Input
                type="time"
                value={at}
                onChange={(e) => setAt(e.target.value)}
                className="w-28"
              />
            ) : (
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Input
                  type="number"
                  min={1}
                  value={minutes}
                  onChange={(e) => setMinutes(Number(e.target.value))}
                  className="w-20"
                />
                min
              </div>
            )}
          </div>
        </div>

        {kind === "invoices" ? (
          <>
            <div className="grid gap-1.5">
              <Label htmlFor="routine-search">Mailbox search (optional)</Label>
              <Input
                id="routine-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="ALL"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="routine-email">Email the summary to (optional)</Label>
              <Input
                id="routine-email"
                value={emailTo}
                onChange={(e) => setEmailTo(e.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <div className="flex items-center gap-2 sm:col-span-2">
              <Switch
                id="routine-summary"
                checked={emailSummary}
                onCheckedChange={setEmailSummary}
              />
              <Label htmlFor="routine-summary" className="text-sm text-muted-foreground">
                Send the summary by email — risky steps wait for your approval first.
              </Label>
            </div>
          </>
        ) : (
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor="routine-task">Task YAML path</Label>
            <Input
              id="routine-task"
              value={taskPath}
              onChange={(e) => setTaskPath(e.target.value)}
              placeholder="tasks/notepad-gated-demo.yaml"
            />
          </div>
        )}

        <div className="flex gap-2 sm:col-span-2">
          <Button onClick={submit} disabled={create.isPending || !id.trim()}>
            {create.isPending ? "Saving…" : "Save routine"}
          </Button>
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------ routine card ------------------------------ */

function RoutineCard({ routine, agentLabel }: { routine: ApiRoutine; agentLabel: string }) {
  const queryClient = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const runs = useQuery(routineRunsQuery(routine.id, showHistory));

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["routines"] });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.setRoutineEnabled(routine.id, enabled),
    onSuccess: async (_r, enabled) => {
      toast.success(enabled ? "Routine enabled." : "Routine paused.");
      await invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const runNow = useMutation({
    mutationFn: () => api.runRoutineNow(routine.id),
    onSuccess: () => {
      toast.success("Routine is starting. If it hits a risky step it will wait in Approvals.");
      setTimeout(() => void invalidate(), 1500);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const remove = useMutation({
    mutationFn: () => api.removeRoutine(routine.id),
    onSuccess: async () => {
      toast.success("Routine removed.");
      await invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const status = routine.last_status ?? "";
  // A mission owns its routine: the plan lives on the Missions screen, this row only carries the
  // schedule (F7). Editing the task path here would be silently overwritten on the next mission save.
  const isMission = routine.id.startsWith("mission:");

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold">{routine.name}</h2>
              <Badge variant="outline" className="font-medium">
                {isMission ? "Mission" : kindLabel(routine.kind)}
              </Badge>
              {isMission && (
                <Link
                  to="/missions"
                  className="text-xs text-muted-foreground underline underline-offset-2"
                >
                  open mission
                </Link>
              )}
              <Badge variant="outline" className="font-medium">
                {agentLabel}
              </Badge>
              {routine.params.email_summary && (
                <Badge
                  variant="outline"
                  className="border-orange/30 bg-orange/15 font-medium text-orange"
                >
                  Email · gated
                </Badge>
              )}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              <CalendarClock className="mr-1 inline size-3.5 align-[-2px]" />
              {scheduleLabel(routine)} · next {fmt(routine.next_run_at)}
              {routine.last_run_at ? ` · last ${fmt(routine.last_run_at)}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Badge
              variant="outline"
              className={statusStyles[status] ?? "bg-muted text-muted-foreground"}
            >
              {statusLabel(routine.last_status)}
            </Badge>
            <div className="flex items-center gap-1.5">
              <Switch
                checked={routine.enabled}
                onCheckedChange={(value) => toggle.mutate(value)}
                aria-label={routine.enabled ? "Pause routine" : "Enable routine"}
              />
              <span className="text-xs text-muted-foreground">
                {routine.enabled ? "On" : "Off"}
              </span>
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => runNow.mutate()}
            disabled={runNow.isPending}
          >
            <Play className="size-3.5" />
            Run now
          </Button>
          <Button size="sm" variant="outline" onClick={() => setShowHistory((v) => !v)}>
            <History className="size-3.5" />
            {showHistory ? "Hide history" : "History"}
          </Button>
          {confirmRemove ? (
            <>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
              >
                Really remove
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(false)}>
                Keep
              </Button>
            </>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)}>
              <Trash2 className="size-3.5" />
              Remove
            </Button>
          )}
        </div>

        {showHistory && (
          <div className="mt-4 rounded-lg border border-border">
            {runs.isLoading ? (
              <p className="px-4 py-3 text-sm text-muted-foreground">Loading…</p>
            ) : (runs.data ?? []).length === 0 ? (
              <p className="px-4 py-3 text-sm text-muted-foreground">No runs yet.</p>
            ) : (
              <ul className="divide-y divide-border">
                {(runs.data ?? []).map((run) => (
                  <li
                    key={run.id}
                    className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm"
                  >
                    <span className="font-mono text-xs text-muted-foreground">{run.id}</span>
                    <span>{fmt(run.started_at)}</span>
                    <Badge
                      variant="outline"
                      className={statusStyles[run.status ?? ""] ?? "bg-muted text-muted-foreground"}
                    >
                      {statusLabel(run.status)}
                    </Badge>
                    {run.approval_id && (
                      <Link to="/approvals" className="text-xs underline underline-offset-2">
                        {run.approval_id}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* --------------------------------- page ---------------------------------- */

function RoutinesPage() {
  const routines = useQuery(routinesQuery());
  const agents = useQuery(agentsQuery());
  const [showForm, setShowForm] = useState(false);

  return (
    <>
      <AppHeader />
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Routines</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Scheduled runs that work while you don't. Risky steps wait in Approvals before they
              execute; everything else runs on its own.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <RefreshButton
              onRefresh={() => void routines.refetch()}
              refreshing={routines.isFetching}
            />
            <Button size="sm" onClick={() => setShowForm((v) => !v)}>
              <Plus className="size-4" />
              New routine
            </Button>
          </div>
        </div>

        {DEMO_MODE && (
          <p className="mt-4 rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
            Demo mode: routines run on your own machine — this preview shows the shape of the page.
          </p>
        )}

        {showForm && <CreateForm onDone={() => setShowForm(false)} />}

        {routines.isError ? (
          <ErrorState onRetry={() => void routines.refetch()} />
        ) : routines.isLoading ? (
          <RowSkeleton />
        ) : (routines.data ?? []).length === 0 ? (
          <div className="mt-6 rounded-lg border border-dashed p-10 text-center">
            <p className="text-sm font-medium">No routines yet.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Create one — e.g. a daily invoice scan from Gmail.
            </p>
          </div>
        ) : (
          <div className="mt-6 space-y-4">
            {(routines.data ?? []).map((routine) => (
              <RoutineCard
                key={routine.id}
                routine={routine}
                agentLabel={
                  agents.data?.find((agent) => agent.id === routine.agent_id)?.name ??
                  routine.agent_id
                }
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
