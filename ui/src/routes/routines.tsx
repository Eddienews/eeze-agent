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
import { useT, type MessageKey, type Translate } from "@/lib/i18n";

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

function statusLabel(t: Translate, status?: string | null) {
  if (!status) return t("m.neverRan");
  const key = `status.${status}` as MessageKey;
  const label = t(key);
  return label === key ? status.replace(/_/g, " ") : label;
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

function scheduleLabel(routine: ApiRoutine, t: Translate) {
  const s = routine.schedule;
  if (s.type === "daily") return t("rt.dailyAt", { at: s.at ?? "08:00" });
  if (s.type === "every") return t("rt.everyMin", { n: s.minutes ?? "?" });
  if (s.type === "watch") return t("m.sched.watch");
  return s.type;
}

function kindLabel(kind: string, t: Translate) {
  return kind === "invoices" ? t("rt.invoices") : kind === "task" ? t("rt.task") : kind;
}

/* ------------------------------- create panel ------------------------------ */

function CreateForm({ onDone }: { onDone: () => void }) {
  const t = useT();
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
      toast.success(t("rt.saved", { name: routine.name, next: fmt(routine.next_run_at) }));
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
          <Label htmlFor="routine-id">{t("rt.idSlug")}</Label>
          <Input
            id="routine-id"
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="invoices"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="routine-name">{t("m.name")}</Label>
          <Input
            id="routine-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("rt.namePlaceholder")}
          />
        </div>
        <div className="grid gap-1.5">
          <Label>{t("m.kind")}</Label>
          <div className="flex gap-2">
            <Button
              type="button"
              variant={kind === "invoices" ? "default" : "outline"}
              size="sm"
              onClick={() => setKind("invoices")}
            >
              {t("rt.invoices")}
            </Button>
            <Button
              type="button"
              variant={kind === "task" ? "default" : "outline"}
              size="sm"
              onClick={() => setKind("task")}
            >
              {t("rt.taskYaml")}
            </Button>
          </div>
        </div>
        <div className="grid gap-1.5">
          <Label>{t("m.agent")}</Label>
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
          <Label>{t("m.schedule")}</Label>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant={schedType === "daily" ? "default" : "outline"}
              size="sm"
              onClick={() => setSchedType("daily")}
            >
              {t("m.daily")}
            </Button>
            <Button
              type="button"
              variant={schedType === "every" ? "default" : "outline"}
              size="sm"
              onClick={() => setSchedType("every")}
            >
              {t("m.every")}
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
                {t("m.min")}
              </div>
            )}
          </div>
        </div>

        {kind === "invoices" ? (
          <>
            <div className="grid gap-1.5">
              <Label htmlFor="routine-search">{t("rt.search")}</Label>
              <Input
                id="routine-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="ALL"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="routine-email">{t("rt.emailTo")}</Label>
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
                {t("rt.emailSummary")}
              </Label>
            </div>
          </>
        ) : (
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor="routine-task">{t("rt.taskPath")}</Label>
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
            {create.isPending ? t("rt.saving") : t("rt.save")}
          </Button>
          <Button variant="ghost" onClick={onDone}>
            {t("m.cancel")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------ routine card ------------------------------ */

function RoutineCard({ routine, agentLabel }: { routine: ApiRoutine; agentLabel: string }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const runs = useQuery(routineRunsQuery(routine.id, showHistory));

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["routines"] });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.setRoutineEnabled(routine.id, enabled),
    onSuccess: async (_r, enabled) => {
      toast.success(enabled ? t("rt.toast.enabled") : t("rt.toast.paused"));
      await invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const runNow = useMutation({
    mutationFn: () => api.runRoutineNow(routine.id),
    onSuccess: () => {
      toast.success(t("rt.toast.starting"));
      setTimeout(() => void invalidate(), 1500);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const remove = useMutation({
    mutationFn: () => api.removeRoutine(routine.id),
    onSuccess: async () => {
      toast.success(t("rt.toast.removed"));
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
                {isMission ? t("rt.mission") : kindLabel(routine.kind, t)}
              </Badge>
              {isMission && (
                <Link
                  to="/missions"
                  className="text-xs text-muted-foreground underline underline-offset-2"
                >
                  {t("rt.openMission")}
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
                  {t("rt.emailGated")}
                </Badge>
              )}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              <CalendarClock className="mr-1 inline size-3.5 align-[-2px]" />
              {scheduleLabel(routine, t)} · {t("rt.next", { at: fmt(routine.next_run_at) })}
              {routine.last_run_at ? ` · ${t("rt.last", { at: fmt(routine.last_run_at) })}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Badge
              variant="outline"
              className={statusStyles[status] ?? "bg-muted text-muted-foreground"}
            >
              {statusLabel(t, routine.last_status)}
            </Badge>
            <div className="flex items-center gap-1.5">
              <Switch
                checked={routine.enabled}
                onCheckedChange={(value) => toggle.mutate(value)}
                aria-label={routine.enabled ? t("rt.pause") : t("rt.enable")}
              />
              <span className="text-xs text-muted-foreground">
                {routine.enabled ? t("rt.on") : t("rt.off")}
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
            {t("m.runNow")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setShowHistory((v) => !v)}>
            <History className="size-3.5" />
            {showHistory ? t("rt.hideHistory") : t("rt.history")}
          </Button>
          {confirmRemove ? (
            <>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
              >
                {t("rt.reallyRemove")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(false)}>
                {t("rt.keep")}
              </Button>
            </>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)}>
              <Trash2 className="size-3.5" />
              {t("m.remove")}
            </Button>
          )}
        </div>

        {showHistory && (
          <div className="mt-4 rounded-lg border border-border">
            {runs.isLoading ? (
              <p className="px-4 py-3 text-sm text-muted-foreground">{t("rt.loading")}</p>
            ) : (runs.data ?? []).length === 0 ? (
              <p className="px-4 py-3 text-sm text-muted-foreground">{t("rt.noRuns")}</p>
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
                      {statusLabel(t, run.status)}
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
  const t = useT();
  const routines = useQuery(routinesQuery());
  const agents = useQuery(agentsQuery());
  const [showForm, setShowForm] = useState(false);

  return (
    <>
      <AppHeader />
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{t("nav.routines")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("rt.intro")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <RefreshButton
              onRefresh={() => void routines.refetch()}
              refreshing={routines.isFetching}
            />
            <Button size="sm" onClick={() => setShowForm((v) => !v)}>
              <Plus className="size-4" />
              {t("rt.new")}
            </Button>
          </div>
        </div>

        {DEMO_MODE && (
          <p className="mt-4 rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
            {t("rt.demo")}
          </p>
        )}

        {showForm && <CreateForm onDone={() => setShowForm(false)} />}

        {routines.isError ? (
          <ErrorState onRetry={() => void routines.refetch()} />
        ) : routines.isLoading ? (
          <RowSkeleton />
        ) : (routines.data ?? []).length === 0 ? (
          <div className="mt-6 rounded-lg border border-dashed p-10 text-center">
            <p className="text-sm font-medium">{t("rt.none")}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("rt.noneHint")}
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
