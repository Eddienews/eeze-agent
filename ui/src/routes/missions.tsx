import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleX,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ErrorState, RowSkeleton } from "@/components/data-state";
import { LIVE_STATUSES, MissionResults, PlanSummary } from "@/components/mission-preview";
import { FilesPlanPreview } from "@/components/files-preview";
import { FolderPicker } from "@/components/folder-picker";
import { useI18n, useT, type MessageKey, type Translate } from "@/lib/i18n";
import { agentsQuery, missionsQuery } from "@/lib/queries";
import {
  DEMO_MODE,
  api,
  type ApiMission,
  type ApiMissionSchedule,
  type ApiRecipe,
  type MissionKind,
} from "@/lib/api";

type MissionsSearch = { goal?: string; kind?: MissionKind; agent?: string };

const KIND_IDS: MissionKind[] = ["3d", "video", "photo", "task", "files"];

export const Route = createFileRoute("/missions")({
  head: () => ({ meta: [{ title: "Missions — Eeze Agents" }] }),
  // Prefill from the command bar: /missions?goal=...&kind=video (nothing runs from a URL).
  validateSearch: (search: Record<string, unknown>): MissionsSearch => {
    const out: MissionsSearch = {};
    if (typeof search["goal"] === "string" && search["goal"].trim()) {
      out.goal = search["goal"].slice(0, 2000);
    }
    if (typeof search["kind"] === "string" && KIND_IDS.includes(search["kind"] as MissionKind)) {
      out.kind = search["kind"] as MissionKind;
    }
    if (typeof search["agent"] === "string" && /^[a-z0-9_-]{1,40}$/.test(search["agent"])) {
      out.agent = search["agent"];
    }
    return out;
  },
  component: MissionsPage,
});

const KINDS: Array<{ id: MissionKind; label: MessageKey; blurb: MessageKey }> = [
  { id: "files", label: "m.kind.files", blurb: "m.blurb.files" },
  { id: "video", label: "m.kind.video", blurb: "m.blurb.video" },
  { id: "photo", label: "m.kind.photo", blurb: "m.blurb.photo" },
  { id: "3d", label: "m.kind.3d", blurb: "m.blurb.3d" },
  { id: "task", label: "m.kind.task", blurb: "m.blurb.task" },
];

type FormState = {
  id: string;
  name: string;
  kind: MissionKind;
  agent_id: string;
  goal: string;
  sources: string;
  plan: string;
  schedule: ApiMissionSchedule;
};

const EMPTY: FormState = {
  id: "",
  name: "",
  kind: "files",
  agent_id: "default",
  goal: "",
  sources: "",
  plan: "",
  schedule: { type: "on_demand" },
};

const statusStyles: Record<string, string> = {
  ok: "bg-success/12 text-success border-success/25",
  done: "bg-success/12 text-success border-success/25",
  needs_approval: "bg-warning/15 text-warning border-warning/30",
  running: "bg-info/12 text-info border-info/25",
  interrupted: "bg-destructive/12 text-destructive border-destructive/30",
  denied: "bg-muted text-muted-foreground",
  abandoned: "bg-muted text-muted-foreground",
  expired: "bg-muted text-muted-foreground",
  error: "bg-destructive/12 text-destructive border-destructive/30",
  budget_exceeded: "bg-destructive/12 text-destructive border-destructive/30",
};

function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || ""
  );
}

function scheduleLabel(schedule: ApiMissionSchedule | undefined, t: Translate): string {
  if (!schedule || schedule.type === "on_demand") return t("m.sched.onDemand");
  if (schedule.type === "daily") return t("m.sched.daily", { at: schedule.at ?? "08:00" });
  return t("m.sched.every", { n: schedule.minutes ?? 0 });
}

function statusLabel(status: string, t: Translate): string {
  const key = `status.${status}` as MessageKey;
  const text = t(key);
  return text === key ? status.replace(/_/g, " ") : text;
}

function kindLabel(kind: string, t: Translate): string {
  const found = KINDS.find((k) => k.id === kind);
  return found ? t(found.label) : kind;
}

function MissionsPage() {
  const t = useT();
  const { lang } = useI18n();
  const queryClient = useQueryClient();
  // Poll while any mission is running or waiting, so status and results update by themselves.
  const missions = useQuery({
    ...missionsQuery(),
    refetchInterval: (query) => {
      const statuses = (query.state.data ?? []).map((row) => row.last_run?.status ?? "");
      if (statuses.includes("running")) return 3_000;
      if (statuses.some((status) => LIVE_STATUSES.has(status))) return 15_000;
      return false;
    },
  });
  const recipes = useQuery({
    queryKey: ["recipes"],
    queryFn: ({ signal }) => api.recipes(signal),
    enabled: !DEMO_MODE,
    staleTime: Infinity,
  });
  const [showYaml, setShowYaml] = useState(false);
  const agents = useQuery(agentsQuery());
  const [selected, setSelected] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [draftMeta, setDraftMeta] = useState<ApiMission["plan_meta"] | null>(null);
  const [edited, setEdited] = useState(false);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [validation, setValidation] = useState<{ ok: boolean; errors: string[] } | null>(null);
  const [draftRefusal, setDraftRefusal] = useState<{
    message: string;
    attempts: Array<{ attempt: number; error: string | null }>;
  } | null>(null);
  const loadedFor = useRef<string | null>(null);
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  // A request typed in the command bar lands here as a new, unsaved draft.
  useEffect(() => {
    if (!search.goal) return;
    setSelected("new");
    setForm({
      ...EMPTY,
      kind: search.kind ?? "task",
      goal: search.goal,
      agent_id: search.agent ?? "default",
      name: search.goal.split(/\s+/).slice(0, 5).join(" "),
    });
    setDraftMeta(null);
    setEdited(false);
    setValidation(null);
    setDraftRefusal(null);
    setShowYaml(false);
    loadedFor.current = null;
    void navigate({ search: {}, replace: true });
  }, [search.goal, search.kind, search.agent, navigate]);

  const rows = useMemo(() => missions.data ?? [], [missions.data]);
  const existing = rows.find((row) => row.id === selected);

  // Load a saved mission into the editor once (never clobber unsaved edits on refetch).
  const detail = useQuery({
    queryKey: ["missions", "detail", selected ?? ""],
    queryFn: ({ signal }) => api.mission(selected as string, signal),
    enabled: !DEMO_MODE && Boolean(selected) && selected !== "new",
    staleTime: 0,
  });
  useEffect(() => {
    const row = detail.data;
    if (!row || loadedFor.current === row.id) return;
    loadedFor.current = row.id;
    setForm({
      id: row.id,
      name: row.name,
      kind: row.kind,
      agent_id: row.agent_id || "default",
      goal: row.goal,
      sources: row.sources,
      plan: row.plan ?? "",
      schedule: row.schedule ?? { type: "on_demand" },
    });
    setDraftMeta(row.plan_meta ?? null);
    setEdited(Boolean(row.plan_meta?.edited));
    setShowYaml(row.kind === "task");
    setValidation(null);
    setDraftRefusal(null);
    setConfirmRegen(false);
  }, [detail.data]);

  const refreshList = () => void queryClient.invalidateQueries({ queryKey: ["missions"] });

  const draft = useMutation({
    mutationFn: () =>
      api.draftMission({
        kind: form.kind,
        goal: form.goal.trim(),
        name: slugify(form.name) || "mission",
        agent_id: form.agent_id || "default",
        ...(["video", "photo", "files"].includes(form.kind) ? { sources: form.sources.trim() } : {}),
      }),
    onSuccess: (result) => {
      setForm((prev) => ({ ...prev, plan: result.plan }));
      setDraftMeta({
        model: result.model,
        tokens: result.tokens,
        cost_usd: result.cost_usd,
        ms: result.ms,
      });
      setEdited(false);
      setConfirmRegen(false);
      setDraftRefusal(null);
      setValidation(null);
      setShowYaml(form.kind === "task");
      toast.message(t("m.toast.draft"), {
        description: `${result.model} · ${result.ms} ms · ${result.tokens.toLocaleString()} tokens`,
      });
    },
    onError: (error: Error & { envelope?: { detail?: unknown } }) => {
      const detail = error.envelope?.detail as
        { attempts?: Array<{ attempt: number; error: string | null }> } | undefined;
      setDraftRefusal({
        message: error.message,
        attempts: detail?.attempts ?? [],
      });
    },
  });

  const save = useMutation({
    mutationFn: () =>
      api.saveMission({
        id: effectiveId,
        name: form.name.trim() || effectiveId,
        kind: form.kind,
        agent_id: form.agent_id || "default",
        goal: form.goal,
        plan: form.plan,
        sources: form.sources,
        schedule: form.schedule,
      }),
    onSuccess: (row) => {
      toast.success(row.note || t("m.toast.saved", { name: row.name }));
      loadedFor.current = null; // re-load the saved copy (server truth)
      setSelected(row.id);
      setEdited(Boolean(row.plan_meta?.edited));
      refreshList();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const validate = useMutation({
    // Always check the text on screen against the kind on screen (a saved mission may be
    // switching kind in this edit).
    mutationFn: () =>
      api.validateDraft({ kind: form.kind, plan: form.plan, sources: form.sources }),
    onSuccess: (result) => {
      setValidation(result);
      if (result.ok) toast.success(t("m.toast.valid"));
    },
    onError: (error: Error) => toast.error(t("m.toast.checkFail", { msg: error.message })),
  });

  const run = useMutation({
    mutationFn: (id: string) => api.runMission(id),
    onSuccess: () => {
      toast.success(t("m.toast.started"), {
        action: { label: t("nav.approvals"), onClick: () => void navigateTo("/approvals") },
      });
      // The run starts in a separate process: look a few times until it reports "running".
      for (const delay of [1500, 4000, 8000, 15000]) setTimeout(refreshList, delay);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.removeMission(id),
    onSuccess: () => {
      toast.success(t("m.toast.removed"));
      setSelected(null);
      setForm(EMPTY);
      loadedFor.current = null;
      refreshList();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const derivedId = useMemo(() => {
    const base = form.id || slugify(form.name) || slugify(form.goal.slice(0, 40)) || "mission";
    if (!form.name && !form.id) return base;
    const taken = new Set(rows.map((row) => row.id).filter((id) => id !== selected));
    if (!taken.has(base)) return base;
    let n = 2;
    while (taken.has(`${base}-${n}`)) n += 1;
    return `${base}-${n}`;
  }, [form.id, form.name, form.goal, rows, selected]);

  const isNew = selected === null || selected === "new";
  const effectiveId = isNew ? derivedId : form.id;
  const planReady = form.plan.trim().length > 0;
  const goalReady = form.goal.trim().length > 0;
  const kindBlurbKey = KINDS.find((k) => k.id === form.kind)?.blurb;
  const kindBlurb = kindBlurbKey ? t(kindBlurbKey) : "";
  const lastRun = existing?.last_run ?? null;

  const startNew = () => {
    setSelected("new");
    setForm({ ...EMPTY, kind: form.kind });
    setDraftMeta(null);
    setEdited(false);
    setValidation(null);
    setDraftRefusal(null);
    setConfirmRegen(false);
    setConfirmRemove(false);
    setShowYaml(false);
    loadedFor.current = null;
  };

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
        <h1 className="text-xl font-semibold">{t("m.title")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          {t("m.intro1")} <span className="text-foreground">{t("m.intro2")}</span>
          {t("m.intro3")}
        </p>

        <div className="mt-5 grid gap-4 lg:grid-cols-[280px_1fr]">
          <Card>
            <CardContent className="pt-5">
              <Button className="w-full" onClick={startNew}>
                <Plus className="mr-1.5 h-4 w-4" /> {t("m.new")}
              </Button>
              <div className="mt-3 space-y-2">
                {missions.isLoading && <RowSkeleton rows={2} />}
                {missions.isError && (
                  <ErrorState message={t("m.loadError")} onRetry={refreshList} />
                )}
                {!missions.isLoading && rows.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    {t("m.none")}
                  </p>
                )}
                {rows.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    onClick={() => {
                      loadedFor.current = null;
                      setSelected(row.id);
                      setValidation(null);
                      setDraftRefusal(null);
                      setConfirmRemove(false);
                    }}
                    className={`w-full rounded-md border px-3 py-2 text-left transition-colors hover:bg-accent/40 ${
                      selected === row.id ? "border-foreground/60 bg-accent/30" : "border-border"
                    }`}
                  >
                    <span className="block truncate text-sm font-medium">{row.name}</span>
                    <span className="mt-0.5 block text-[11px] text-muted-foreground">
                      {kindLabel(row.kind, t)} · {scheduleLabel(row.schedule, t)} ·{" "}
                      {row.last_run ? statusLabel(row.last_run.status, t) : t("m.neverRan")}
                      {!row.has_plan && ` · ${t("m.noPlan")}`}
                    </span>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="mission-name">{t("m.name")}</Label>
                  <Input
                    id="mission-name"
                    value={form.name}
                    placeholder={t("m.namePlaceholder")}
                    onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                  />
                  <span className="text-[11px] text-muted-foreground">
                    {t("m.savedAs", { id: effectiveId || "—" })}
                  </span>
                </div>
                <div className="grid gap-1.5">
                  <Label>{t("m.kind")}</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {KINDS.map((kind) => (
                      <Button
                        key={kind.id}
                        type="button"
                        size="sm"
                        variant={form.kind === kind.id ? "default" : "outline"}
                        onClick={() => {
                          if (kind.id === form.kind) return;
                          if (form.plan.trim()) {
                            toast.message(t("m.toast.kindCleared"), {
                              description: t("m.toast.kindClearedHint"),
                            });
                          }
                          setForm((prev) => ({ ...prev, kind: kind.id, plan: "" }));
                        }}
                      >
                        {t(kind.label)}
                      </Button>
                    ))}
                  </div>
                  <span className="text-[11px] text-muted-foreground">{kindBlurb}</span>
                </div>
                <div className="grid gap-1.5">
                  <Label>{t("m.agent")}</Label>
                  <Select
                    value={form.agent_id}
                    onValueChange={(value) => setForm((prev) => ({ ...prev, agent_id: value }))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="default" />
                    </SelectTrigger>
                    <SelectContent>
                      {(agents.data ?? []).length === 0 && (
                        <SelectItem value="default">{t("m2.defaultAgent")}</SelectItem>
                      )}
                      {(agents.data ?? []).map((agent) => (
                        <SelectItem key={agent.id} value={agent.id}>
                          {agent.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-1.5">
                  <Label>{t("m.schedule")}</Label>
                  <div className="flex items-center gap-1.5">
                    <Select
                      value={form.schedule.type}
                      onValueChange={(value) =>
                        setForm((prev) => ({
                          ...prev,
                          schedule:
                            value === "daily"
                              ? { type: "daily", at: prev.schedule.at ?? "08:00" }
                              : value === "every"
                                ? { type: "every", minutes: prev.schedule.minutes ?? 60 }
                                : { type: "on_demand" },
                        }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="on_demand">{t("m.onDemand")}</SelectItem>
                        <SelectItem value="daily">{t("m.daily")}</SelectItem>
                        <SelectItem value="every">{t("m.every")}</SelectItem>
                      </SelectContent>
                    </Select>
                    {form.schedule.type === "daily" && (
                      <Input
                        type="time"
                        className="w-28"
                        value={form.schedule.at ?? "08:00"}
                        onChange={(event) =>
                          setForm((prev) => ({
                            ...prev,
                            schedule: { type: "daily", at: event.target.value },
                          }))
                        }
                      />
                    )}
                    {form.schedule.type === "every" && (
                      <>
                        <Input
                          type="number"
                          min={1}
                          className="w-20"
                          value={form.schedule.minutes ?? 60}
                          onChange={(event) =>
                            setForm((prev) => ({
                              ...prev,
                              schedule: { type: "every", minutes: Number(event.target.value) || 1 },
                            }))
                          }
                        />
                        <span className="text-xs text-muted-foreground">{t("m.min")}</span>
                      </>
                    )}
                  </div>
                </div>
                {(form.kind === "video" || form.kind === "photo" || form.kind === "files") && (
                  <div className="grid gap-1.5 sm:col-span-2">
                    <Label htmlFor="mission-sources">
                      {form.kind === "photo"
                        ? t("m.src.photo")
                        : form.kind === "files"
                          ? t("m.src.files")
                          : t("m.src.video")}
                    </Label>
                    <div className="flex gap-2">
                    <Input
                      id="mission-sources"
                      value={form.sources}
                      placeholder={
                        form.kind === "photo"
                          ? "C:\\Users\\you\\Pictures\\photo.png"
                          : form.kind === "files"
                            ? "C:\\Users\\you\\Pictures\\Trip"
                            : "C:\\Users\\you\\clips\\teaser"
                      }
                      onChange={(event) =>
                        setForm((prev) => ({ ...prev, sources: event.target.value }))
                      }
                    />
                    <FolderPicker
                      value={form.sources}
                      allowFiles={form.kind !== "files"}
                      onPick={(path) => setForm((prev) => ({ ...prev, sources: path }))}
                    />
                    </div>
                    <span className="text-[11px] text-muted-foreground">
                      {form.kind === "photo"
                        ? t("m.src.photoHint")
                        : form.kind === "files"
                          ? t("m.src.filesHint")
                          : t("m.src.videoHint")}
                    </span>
                  </div>
                )}
              </div>

              {isNew && !form.goal.trim() && (recipes.data ?? []).length > 0 && (
                <div className="mt-5">
                  <p className="text-xs font-medium">
                    {t("m.recipes")}{" "}
                    <span className="font-normal text-muted-foreground">{t("m.recipesHint")}</span>
                  </p>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {(recipes.data ?? []).map((recipe: ApiRecipe) => (
                      <button
                        key={recipe.id}
                        type="button"
                        onClick={() =>
                          setForm((prev) => ({
                            ...prev,
                            kind: recipe.kind,
                            name: lang === "pt" && recipe.name_pt ? recipe.name_pt : recipe.name,
                            goal: lang === "pt" && recipe.goal_pt ? recipe.goal_pt : recipe.goal,
                            plan: "",
                          }))
                        }
                        className="rounded-md border border-border px-3 py-2 text-left transition-colors hover:border-foreground/40 hover:bg-accent/40"
                      >
                        <span className="block text-sm font-medium">
                          {lang === "pt" && recipe.title_pt ? recipe.title_pt : recipe.title}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-muted-foreground">
                          {kindLabel(recipe.kind, t)} ·{" "}
                          {lang === "pt" && recipe.blurb_pt ? recipe.blurb_pt : recipe.blurb}
                          {recipe.needs_sources ? ` · ${t("m.needsFolder")}` : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-5">
                <p className="text-xs font-medium">
                  {t("m.step1")}{" "}
                  <span className="font-normal text-muted-foreground">{t("m.step1Hint")}</span>
                </p>
                <Textarea
                  className="mt-2 min-h-[64px]"
                  value={form.goal}
                  onChange={(event) => setForm((prev) => ({ ...prev, goal: event.target.value }))}
                  placeholder={t("m.goalPlaceholder")}
                />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!goalReady || draft.isPending || confirmRegen}
                    onClick={() => {
                      if (planReady && form.plan !== "" && (edited || draftMeta)) {
                        setConfirmRegen(true);
                        return;
                      }
                      draft.mutate();
                    }}
                  >
                    <Wand2 className="mr-1.5 h-4 w-4" />
                    {draft.isPending
                      ? t("m.writing")
                      : draftMeta
                        ? t("m.regenerate")
                        : t("m.generate")}
                  </Button>
                  <span className="text-[11px] text-muted-foreground">
                    {goalReady ? t("m.generateHint") : t("m.goalFirst")}
                  </span>
                </div>
                {confirmRegen && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs">
                    <span>{t("m.regenWarn")}</span>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setConfirmRegen(false);
                        draft.mutate();
                      }}
                    >
                      {t("m.regenAnyway")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmRegen(false)}>
                      {t("m.keepText")}
                    </Button>
                  </div>
                )}
                {draftRefusal && (
                  <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs">
                    <p className="font-medium">{t("m.refused", { msg: draftRefusal.message })}</p>
                    {draftRefusal.attempts.length > 0 && (
                      <ul className="mt-1 list-disc pl-4 text-muted-foreground">
                        {draftRefusal.attempts.map((attempt) => (
                          <li key={attempt.attempt}>
                            {t("m.attempt", { n: attempt.attempt, err: attempt.error ?? t("m.rejected") })}
                          </li>
                        ))}
                      </ul>
                    )}
                    <p className="mt-1 text-muted-foreground">
                      {t("m.refusedHint")}
                    </p>
                  </div>
                )}
              </div>

              <div className="mt-5">
                <p className="flex flex-wrap items-center gap-1.5 text-xs font-medium">
                  {t("m.step2")}
                  <span className="font-normal text-muted-foreground">{t("m.step2Hint")}</span>
                  {draftMeta && (
                    <Badge variant="outline" className="font-normal">
                      draft · {draftMeta.model ?? "?"} · {draftMeta.tokens?.toLocaleString() ?? 0}{" "}
                      tokens · {draftMeta.ms ?? 0} ms
                      {typeof draftMeta.cost_usd === "number"
                        ? ` · $${draftMeta.cost_usd.toFixed(4)}`
                        : ""}
                    </Badge>
                  )}
                  {edited && (
                    <Badge variant="outline" className="border-foreground/40 font-normal">
                      {t("m.edited")}
                    </Badge>
                  )}
                </p>
                {planReady && (
                  <div className="mt-2 rounded-md border border-border bg-muted/30 p-3">
                    <PlanSummary kind={form.kind} plan={form.plan} />
                    {form.kind === "files" && (
                      <div className="mt-3">
                        <FilesPlanPreview plan={form.plan} />
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => setShowYaml((value) => !value)}
                      className="mt-2 flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
                    >
                      {showYaml ? (
                        <ChevronDown className="size-3" />
                      ) : (
                        <ChevronRight className="size-3" />
                      )}
                      {t("m.advanced", { action: showYaml ? t("m.advHide") : t("m.advShow") })}
                    </button>
                  </div>
                )}
                <Textarea
                  hidden={planReady && !showYaml}
                  className="mt-2 min-h-[260px] font-mono text-xs leading-relaxed"
                  spellCheck={false}
                  value={form.plan}
                  onChange={(event) => {
                    setForm((prev) => ({ ...prev, plan: event.target.value }));
                    setEdited(true);
                    setValidation(null);
                  }}
                  placeholder={t("m.planPlaceholder")}
                />
                {validation && (
                  <div
                    className={`mt-2 rounded-md border px-3 py-2 text-xs ${
                      validation.ok
                        ? "border-success/30 bg-success/10"
                        : "border-destructive/30 bg-destructive/10"
                    }`}
                  >
                    {validation.ok ? (
                      <p className="flex items-center gap-1.5">
                        <CircleCheck className="h-3.5 w-3.5" /> {t("m.valid")}
                      </p>
                    ) : (
                      <div>
                        <p className="flex items-center gap-1.5 font-medium">
                          <CircleX className="h-3.5 w-3.5" />{" "}
                          {t("m.problems", { n: validation.errors.length })}
                        </p>
                        <ul className="mt-1 list-disc pl-4 text-muted-foreground">
                          {validation.errors.map((error, index) => (
                            <li key={index} className="break-words">
                              {error}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!planReady || validate.isPending}
                    onClick={() => validate.mutate()}
                  >
                    {validate.isPending ? t("m.checking") : t("m.validate")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      !planReady || save.isPending || (!isNew && !form.name.trim() && !form.id)
                    }
                    onClick={() => save.mutate()}
                  >
                    <Save className="mr-1.5 h-4 w-4" /> {t("m.save")}
                  </Button>
                  <Button
                    size="sm"
                    disabled={!planReady || save.isPending || validate.isPending || run.isPending}
                    onClick={() =>
                      // Check first: a plan the runner would refuse should never reach Approvals.
                      validate.mutateAsync().then(
                        (result) => {
                          if (!result.ok) {
                            setShowYaml(true);
                            toast.error(t("m.toast.fixFirst"));
                            return;
                          }
                          return save.mutateAsync().then(
                            (row) => run.mutate(row.id),
                            () => undefined,
                          );
                        },
                        () => undefined,
                      )
                    }
                  >
                    <Sparkles className="mr-1.5 h-4 w-4" /> {t("m.saveRun")}
                  </Button>
                  {planReady ? (
                    <span className="text-[11px] text-muted-foreground">
                      {t("m.saveRunHint")}
                    </span>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">
                      {t("m.runAfterPlan")}
                    </span>
                  )}
                </div>
              </div>

              {!isNew && existing && (
                <div className="mt-5 flex flex-wrap items-center gap-3 border-t pt-4 text-xs">
                  <span className="text-muted-foreground">{t("m.lastRun")}</span>
                  <Badge variant="outline" className={statusStyles[lastRun?.status ?? ""] ?? ""}>
                    {lastRun ? statusLabel(lastRun.status, t) : t("m.neverRan")}
                  </Badge>
                  {lastRun?.runset_id && (
                    <Link
                      to="/demo/agents/$agentId/runs/$runId"
                      params={{ agentId: form.agent_id || "default", runId: lastRun.runset_id }}
                      className="underline underline-offset-2"
                    >
                      {t("m.openRun")}
                    </Link>
                  )}
                  {lastRun?.status === "needs_approval" && (
                    <Link to="/approvals" className="underline underline-offset-2">
                      {t("m.decide")}
                    </Link>
                  )}
                  <Button size="sm" variant="outline" onClick={() => run.mutate(form.id)}>
                    {t("m.runNow")}
                  </Button>
                  {confirmRemove ? (
                    <>
                      <span className="text-muted-foreground">
                        {t("m.removeQ", { name: existing.name })}
                      </span>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => remove.mutate(form.id)}
                      >
                        {t("m.remove")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(false)}>
                        {t("m.cancel")}
                      </Button>
                    </>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)}>
                      <Trash2 className="mr-1.5 h-4 w-4" /> {t("m.remove")}
                    </Button>
                  )}
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("m.refresh")}
                    title={t("m.refresh")}
                    onClick={() => {
                      refreshList();
                      void queryClient.invalidateQueries({ queryKey: ["missions", form.id, "outputs"] });
                    }}
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )}
              {!isNew && existing && (
                <MissionResults missionId={form.id} status={lastRun?.status ?? null} />
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}

/** Small wrapper so the toast action can navigate without pulling the router into every handler. */
async function navigateTo(path: string) {
  if (typeof window !== "undefined") window.location.assign(path);
}
