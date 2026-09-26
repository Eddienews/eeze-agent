import { useEffect, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  ArrowLeft,
  BrainCircuit,
  Check,
  Circle,
  Download,
  Keyboard,
  Monitor,
  MousePointer2,
  Pause,
  Play,
  RotateCcw,
  ScanSearch,
  ScrollText,
  Square,
  TextCursorInput,
} from "lucide-react";
import { AgentAvatar } from "@/components/agent-avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { agents as mockAgents, getAgent } from "@/lib/mock-data";
import { useQuery } from "@tanstack/react-query";
import { RefreshButton } from "@/components/data-state";
import { runQuery } from "@/lib/queries";
import { DEMO_MODE, mapRun, type ApiRunStep } from "@/lib/api";

const titleizeId = (value: string) =>
  value.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

type StepStatus = "success" | "failed";
type StepType = "scan" | "click" | "type" | "scroll";
type RunStep = {
  id: number;
  time: string;
  type: StepType;
  description: string;
  status: StepStatus;
  question: string;
  answer: string;
  confidence: number;
  target: string;
  box: { left: string; top: string; width: string; height: string };
  artifacts?: string[];
};

const mockSteps: RunStep[] = [
  {
    id: 1,
    time: "00:02",
    type: "scan",
    description: "Scanned Xero reconciliation workspace",
    status: "success",
    question: "What workspace is currently visible?",
    answer: "Xero bank reconciliation with 42 pending items.",
    confidence: 0.99,
    target: "workspace",
    box: { left: "4%", top: "14%", width: "92%", height: "76%" },
  },
  {
    id: 2,
    time: "00:11",
    type: "click",
    description: "Clicked account selector c12",
    status: "success",
    question: "Which account should be reconciled?",
    answer: "Select Business Checking · 8842.",
    confidence: 0.98,
    target: "account selector",
    box: { left: "8%", top: "19%", width: "35%", height: "10%" },
  },
  {
    id: 3,
    time: "00:19",
    type: "click",
    description: "Opened 42 unreconciled items",
    status: "success",
    question: "Where are the pending transactions?",
    answer: "Open the Reconcile tab showing 42 items.",
    confidence: 0.97,
    target: "reconcile tab",
    box: { left: "47%", top: "19%", width: "22%", height: "10%" },
  },
  {
    id: 4,
    time: "00:31",
    type: "scroll",
    description: "Scrolled invoice table to newest entries",
    status: "success",
    question: "Which ordering reduces matching errors?",
    answer: "Review newest bank-feed entries first.",
    confidence: 0.91,
    target: "invoice table",
    box: { left: "5%", top: "34%", width: "90%", height: "49%" },
  },
  {
    id: 5,
    time: "00:46",
    type: "click",
    description: "Selected invoice INV-2291",
    status: "success",
    question: "Which invoice matches the €2,480 debit?",
    answer: "INV-2291 from ACME BV matches amount and date.",
    confidence: 0.96,
    target: "INV-2291",
    box: { left: "7%", top: "43%", width: "86%", height: "12%" },
  },
  {
    id: 6,
    time: "01:03",
    type: "type",
    description: "Typed vendor reference ACME BV",
    status: "success",
    question: "How should the vendor be verified?",
    answer: "Search ACME BV and compare its tax ID.",
    confidence: 0.94,
    target: "vendor search",
    box: { left: "58%", top: "58%", width: "34%", height: "9%" },
  },
  {
    id: 7,
    time: "01:26",
    type: "click",
    description: "Clicked Match for INV-2291",
    status: "success",
    question: "Is this match safe to apply?",
    answer: "Yes. Vendor, amount, currency and due date align.",
    confidence: 0.93,
    target: "match button",
    box: { left: "73%", top: "72%", width: "18%", height: "9%" },
  },
  {
    id: 8,
    time: "01:51",
    type: "scan",
    description: "Validated tax and currency fields",
    status: "success",
    question: "Are there accounting inconsistencies?",
    answer: "No tax or currency mismatch detected.",
    confidence: 0.95,
    target: "tax fields",
    box: { left: "36%", top: "42%", width: "29%", height: "25%" },
  },
  {
    id: 9,
    time: "02:15",
    type: "scroll",
    description: "Scrolled to next unmatched invoice",
    status: "success",
    question: "What should be processed next?",
    answer: "Continue to the next high-confidence match.",
    confidence: 0.9,
    target: "next invoice",
    box: { left: "7%", top: "56%", width: "86%", height: "12%" },
  },
  {
    id: 10,
    time: "02:39",
    type: "click",
    description: "Selected invoice INV-2294",
    status: "success",
    question: "Does INV-2294 have a bank-feed candidate?",
    answer: "Candidate found with exact amount and one-day offset.",
    confidence: 0.89,
    target: "INV-2294",
    box: { left: "7%", top: "56%", width: "86%", height: "12%" },
  },
  {
    id: 11,
    time: "03:06",
    type: "type",
    description: "Added reconciliation note",
    status: "success",
    question: "Should the date difference be documented?",
    answer: "Yes. Add a one-day settlement delay note.",
    confidence: 0.92,
    target: "note field",
    box: { left: "36%", top: "69%", width: "34%", height: "10%" },
  },
  {
    id: 12,
    time: "03:48",
    type: "click",
    description: "Requested approval for payment match",
    status: "success",
    question: "Can the final action execute autonomously?",
    answer: "No. Payment policy requires human approval.",
    confidence: 0.97,
    target: "request approval",
    box: { left: "71%", top: "72%", width: "21%", height: "9%" },
  },
];

const stepTypes: StepType[] = ["scan", "click", "type", "scroll"];

function mapSteps(raw: ApiRunStep[]): RunStep[] {
  let elapsed = 0;
  return raw.map((item, index) => {
    const label = `${item.action ?? ""} ${item.id ?? ""}`.toLowerCase();
    const type = (stepTypes.find((candidate) => label.includes(candidate)) ??
      (item.write_method ? "type" : "click")) as StepType;
    const seconds = Math.round(elapsed / 1000);
    elapsed += item.ms ?? 0;
    const target = item.selected ?? item.target ?? "element";
    const describe = item.intent || item.action || String(item.id ?? `Step ${index + 1}`);
    return {
      id: item.index ?? index + 1,
      time: `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`,
      type,
      description: `${describe.replace(/[_-]+/g, " ")} — ${target}`,
      status:
        item.ok === false || (item.status ?? "").toLowerCase() === "failed" ? "failed" : "success",
      question: item.judgment?.question ?? item.judgment_question ?? "No recorded question.",
      answer:
        item.judgment?.answer ??
        item.judgment_answer ??
        item.verification ??
        "No recorded judgment.",
      confidence: item.judgment?.confidence ?? item.confidence ?? 0,
      target: item.judgment?.answer ?? target,
      box: mockSteps[index % mockSteps.length]!.box,
      artifacts: item.artifacts ?? [],
    };
  });
}

export const Route = createFileRoute("/demo/agents/$agentId_/runs/$runId")({
  loader: ({ params }) => {
    const agent = getAgent(params.agentId) ?? {
      ...mockAgents[0]!,
      id: params.agentId,
      name: titleizeId(params.agentId),
      role: "Agent",
    };
    const run = agent.history.find((item) => item.id === params.runId) ?? {
      id: params.runId,
      task: params.runId,
      startedAt: "—",
      duration: "—",
      steps: 0,
      cost: 0,
      outcome: "success" as const,
    };
    return { agent, run };
  },
  head: ({ loaderData }) => {
    const title = loaderData
      ? `${loaderData.run.task} — Run Viewer · Eeze Agents`
      : "Run unavailable — Eeze Agents";
    const description = loaderData
      ? `Inspect ${loaderData.agent.name}'s execution, decisions, duration and cost.`
      : "The requested run is unavailable.";
    return {
      meta: [
        { title },
        { name: "description", content: description },
        { property: "og:title", content: title },
        { property: "og:description", content: description },
        { property: "og:type", content: "website" },
        { name: "twitter:card", content: "summary" },
      ],
    };
  },
  component: RunViewer,
});

function RunViewer() {
  const { agentId, runId } = Route.useParams();
  const { agent: loaderAgent, run: loaderRun } = Route.useLoaderData();
  const runResult = useQuery(runQuery(runId));
  const liveRun = runResult.data ? mapRun(runResult.data) : null;
  const run = liveRun ?? loaderRun;
  const agent = loaderAgent;
  const apiSteps = runResult.data?.steps?.length ? mapSteps(runResult.data.steps) : null;
  const steps = apiSteps ?? (DEMO_MODE ? mockSteps : []);
  const [selected, setSelected] = useState(run.outcome === "running" ? 7 : steps.length - 1);
  const [state, setState] = useState<"running" | "paused" | "stopped" | "completed">(
    run.outcome === "running" ? "running" : run.outcome === "success" ? "completed" : "stopped",
  );
  useEffect(() => {
    setSelected(steps.length - 1);
  }, [steps.length]);
  const [mobilePanel, setMobilePanel] = useState<"screen" | "actions" | "decisions">("screen");
  useEffect(() => {
    if (state !== "running" || selected >= steps.length - 1) return;
    const timer = window.setTimeout(
      () => setSelected((value) => Math.min(value + 1, steps.length - 1)),
      1200,
    );
    return () => window.clearTimeout(timer);
  }, [selected, state]);
  useEffect(() => {
    if (state === "running" && selected === steps.length - 1) setState("completed");
  }, [selected, state]);
  const index = Math.min(selected, steps.length - 1);
  const step = steps[index];
  if (!step)
    return (
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <div className="rounded-md border bg-card p-6 text-sm leading-6 text-muted-foreground">
          No recorded steps for this run — it may have paused before finishing a step, or the runset
          predates step records.{" "}
          {run.journalUrl ? (
            <a className="underline" href={run.journalUrl}>
              Open the raw journal
            </a>
          ) : null}
        </div>
      </div>
    );

  const exportLog = () => {
    const blob = new Blob(
      [JSON.stringify({ agent: agent.name, task: run.task, status: state, steps }, null, 2)],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${agent.id}-${run.id}-audit-log.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    toast.success("Audit log exported");
  };

  return (
    <div className="mx-auto max-w-[1600px] px-3 py-5 pb-24 sm:px-6 xl:pb-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2 mb-4 text-muted-foreground">
        <Link to="/demo/agents/$agentId" params={{ agentId }}>
          <ArrowLeft />
          Back to {agent.name}
        </Link>
      </Button>
      <header className="mb-5 flex flex-col gap-4 border-b pb-5 xl:flex-row xl:items-center">
        <div className="flex min-w-0 items-center gap-3">
          <AgentAvatar name={agent.name} accent={agent.accent} size="md" />
          <div className="min-w-0">
            <p className="text-xs font-medium text-muted-foreground">
              {agent.name} · {agent.role}
            </p>
            <h1 className="truncate text-xl font-semibold">{run.task}</h1>
          </div>
        </div>
        <div className="flex flex-1 flex-wrap items-center gap-2 xl:justify-end">
          <RunBadge state={state} />
          <span className="font-mono text-xs text-muted-foreground">{step.time} elapsed</span>
          <span className="mx-1 hidden h-5 w-px bg-border sm:block" />
          <Metric
            label="Cost"
            value={`$${(run.cost * ((selected + 1) / steps.length)).toFixed(2)}`}
          />
          <Metric label="Steps" value={`${selected + 1} / ${steps.length}`} />
          <Button
            size="sm"
            variant="outline"
            disabled={state === "completed" || state === "stopped"}
            onClick={() => setState(state === "paused" ? "running" : "paused")}
          >
            {state === "paused" ? <Play /> : <Pause />}
            {state === "paused" ? "Resume" : "Pause"}
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={state === "stopped" || state === "completed"}
            onClick={() => {
              setState("stopped");
              toast.info("Run stopped");
            }}
          >
            <Square />
            Stop
          </Button>
        </div>
      </header>

      <main className="grid overflow-hidden rounded-md border bg-border xl:min-h-[600px] xl:grid-cols-[1.25fr_.85fr_.9fr] xl:gap-px">
        <section
          className={`${mobilePanel === "screen" ? "block" : "hidden"} min-w-0 bg-card p-3 sm:p-4 xl:block`}
        >
          <PanelTitle title="Screen View" meta={`Step ${step.id} of ${steps.length}`} />
          {DEMO_MODE ? <Screen step={step} /> : <LiveScreen step={step} runsetId={run.runsetId} />}
          <StepTimeline steps={steps} selected={index} onSelect={setSelected} compact />
        </section>
        <section
          className={`${mobilePanel === "actions" ? "block" : "hidden"} min-w-0 bg-card xl:block`}
        >
          <div className="p-4 pb-2">
            <PanelTitle title="Action Log" meta={`${steps.length} events`} />
          </div>
          <div className="max-h-[560px] overflow-y-auto px-2 pb-3">
            {steps.map((item, index) => (
              <ActionRow
                key={item.id}
                step={item}
                active={index === selected}
                onClick={() => setSelected(index)}
              />
            ))}
          </div>
        </section>
        <section
          className={`${mobilePanel === "decisions" ? "block" : "hidden"} min-w-0 bg-card p-4 xl:block`}
        >
          <PanelTitle title="Jev Decisions" meta={`Cycle ${step.id}`} />
          <div className="mt-4 space-y-4">
            <Decision label="Question" text={step.question} />
            <Decision label="Response" text={step.answer} />
            <div className="rounded-md border bg-muted/40 p-4">
              <div className="flex items-center justify-between gap-4">
                <span className="font-mono text-xs text-muted-foreground">Select element</span>
                <Badge variant="outline" className="font-mono">
                  {step.target}
                </Badge>
              </div>
              <div className="mt-4 flex items-center gap-3">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-success transition-all"
                    style={{ width: `${step.confidence * 100}%` }}
                  />
                </div>
                <span className="font-mono text-xs font-medium">{step.confidence.toFixed(2)}</span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Confidence</p>
            </div>
          </div>
        </section>
      </main>

      <footer className="mt-4 rounded-md border bg-card p-3 sm:p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
          <div className="flex gap-2">
            <RefreshButton
              onRefresh={() => void runResult.refetch()}
              refreshing={runResult.isFetching}
            />
            <Button
              size="sm"
              onClick={() => {
                setSelected(0);
                setState("running");
              }}
            >
              <RotateCcw />
              Replay
            </Button>
            <Button size="sm" variant="outline" onClick={exportLog}>
              <Download />
              Export log
            </Button>
          </div>
          <div className="min-w-0 flex-1 overflow-x-auto pb-1">
            <div className="min-w-[520px]">
              <StepTimeline steps={steps} selected={index} onSelect={setSelected} />
            </div>
          </div>
          <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
            {step.time} / {run.duration}
          </span>
        </div>
      </footer>
      <nav
        aria-label="Run viewer panels"
        className="fixed inset-x-3 bottom-3 z-40 grid grid-cols-3 gap-1 rounded-md border bg-background/95 p-1 shadow-lg backdrop-blur xl:hidden"
      >
        {(
          [
            { id: "screen", label: "Screen", icon: Monitor },
            { id: "actions", label: "Actions", icon: ScrollText },
            { id: "decisions", label: "Decisions", icon: BrainCircuit },
          ] as const
        ).map(({ id, label, icon: Icon }) => (
          <Button
            key={id}
            size="sm"
            variant={mobilePanel === id ? "secondary" : "ghost"}
            onClick={() => setMobilePanel(id)}
            aria-pressed={mobilePanel === id}
            className="gap-1.5"
          >
            <Icon className="size-4" />
            {label}
          </Button>
        ))}
      </nav>
    </div>
  );
}

function PanelTitle({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold">{title}</h2>
      <span className="font-mono text-[11px] text-muted-foreground">{meta}</span>
    </div>
  );
}
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="font-mono text-xs font-semibold">{value}</p>
    </div>
  );
}
function RunBadge({ state }: { state: "running" | "paused" | "stopped" | "completed" }) {
  const label = state === "stopped" ? "Failed" : state[0]?.toUpperCase() + state.slice(1);
  return (
    <Badge
      variant="outline"
      className={
        state === "running"
          ? "border-info/30 bg-info/12 text-info"
          : state === "completed"
            ? "border-success/30 bg-success/12 text-success"
            : state === "stopped"
              ? "border-destructive/30 bg-destructive/12 text-destructive"
              : "border-warning/30 bg-warning/12 text-warning"
      }
    >
      <Circle className="size-1.5 fill-current" />
      {label}
    </Badge>
  );
}
function ActionIcon({ type }: { type: StepType }) {
  const Icon =
    type === "click"
      ? MousePointer2
      : type === "type"
        ? TextCursorInput
        : type === "scroll"
          ? Keyboard
          : ScanSearch;
  return <Icon className="size-4" />;
}
function ActionRow({
  step,
  active,
  onClick,
}: {
  step: RunStep;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      aria-pressed={active}
      className={`h-auto w-full justify-start gap-3 rounded-md px-3 py-3 text-left ${active ? "bg-accent" : ""}`}
    >
      <span
        className={`grid size-8 shrink-0 place-items-center rounded-md ${active ? "bg-info/15 text-info" : "bg-muted text-muted-foreground"}`}
      >
        <ActionIcon type={step.type} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">{step.time}</span>
          <span className="text-xs uppercase text-muted-foreground">{step.type}</span>
        </span>
        <span className="mt-1 block whitespace-normal text-xs leading-5">{step.description}</span>
      </span>
      {step.status === "success" ? (
        <Check className="size-3.5 shrink-0 text-success" />
      ) : (
        <Circle className="size-3.5 shrink-0 text-destructive" />
      )}
    </Button>
  );
}
function Decision({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <p className="mb-2 text-[10px] font-medium uppercase text-muted-foreground">{label}</p>
      <p className="rounded-md border bg-muted/30 p-3 text-sm leading-6">{text}</p>
    </div>
  );
}
function StepTimeline({
  steps,
  selected,
  onSelect,
  compact = false,
}: {
  steps: RunStep[];
  selected: number;
  onSelect: (index: number) => void;
  compact?: boolean;
}) {
  return (
    <nav aria-label="Run step timeline" className={compact ? "mt-4 overflow-x-auto pb-1" : ""}>
      <div className="relative flex min-w-[300px] items-center justify-between">
        <div className="absolute left-1 right-1 top-1/2 h-px bg-border" />
        <div
          className="absolute left-1 top-1/2 h-px bg-info transition-all"
          style={{ width: `${(selected / (steps.length - 1)) * 96}%` }}
        />
        {steps.map((item, index) => (
          <Button
            key={item.id}
            variant="ghost"
            size="icon"
            aria-label={`View step ${item.id}`}
            aria-current={index === selected ? "step" : undefined}
            onClick={() => onSelect(index)}
            className={`${compact ? "size-6" : "size-7"} relative rounded-full p-0`}
          >
            <span
              className={`grid rounded-full border text-[9px] font-medium transition-all ${compact ? "size-4" : "size-5"} ${index === selected ? "border-info bg-info text-info-foreground" : index < selected ? "border-info bg-card text-info" : "border-border bg-card text-muted-foreground"}`}
            >
              {compact ? "" : item.id}
            </span>
          </Button>
        ))}
      </div>
      {compact && (
        <div className="mt-1 flex min-w-[300px] justify-between font-mono text-[9px] text-muted-foreground">
          <span>01</span>
          <span>06</span>
          <span>12</span>
        </div>
      )}
    </nav>
  );
}
function Screen({ step }: { step: RunStep }) {
  return (
    <div className="relative mt-4 aspect-[16/10] min-h-[220px] overflow-hidden rounded-md border bg-surface sm:min-h-[320px]">
      <div className="flex h-8 items-center gap-1.5 border-b bg-card px-3">
        <Circle className="size-2 fill-destructive text-destructive" />
        <Circle className="size-2 fill-warning text-warning" />
        <Circle className="size-2 fill-success text-success" />
        <span className="ml-3 font-mono text-[9px] text-muted-foreground">
          go.xero.com/reconcile
        </span>
      </div>
      <div className="flex h-[calc(100%-2rem)]">
        <aside className="w-10 border-r bg-card p-2 sm:w-14">
          <div className="mb-4 grid size-6 place-items-center rounded bg-info text-[10px] font-bold text-info-foreground sm:size-7">
            X
          </div>
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="mb-3 h-2 rounded bg-muted" />
          ))}
        </aside>
        <div className="min-w-0 flex-1 p-2 sm:p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="h-2 w-20 rounded bg-foreground/70 sm:w-28" />
              <div className="mt-2 h-1.5 w-16 rounded bg-muted-foreground/30 sm:w-20" />
            </div>
            <div className="h-7 w-16 rounded border bg-card sm:h-8 sm:w-28" />
          </div>
          <div className="mt-3 grid grid-cols-3 gap-1 sm:mt-5 sm:gap-2">
            <div className="rounded border bg-card p-2 sm:p-3">
              <div className="h-1.5 w-8 rounded bg-muted sm:w-12" />
              <div className="mt-2 h-3 w-10 rounded bg-foreground/60 sm:w-20" />
            </div>
            <div className="rounded border bg-card p-2 sm:p-3">
              <div className="h-1.5 w-8 rounded bg-muted sm:w-12" />
              <div className="mt-2 h-3 w-10 rounded bg-foreground/60 sm:w-16" />
            </div>
            <div className="rounded border bg-card p-2 sm:p-3">
              <div className="h-1.5 w-8 rounded bg-muted sm:w-12" />
              <div className="mt-2 h-3 w-9 rounded bg-foreground/60 sm:w-14" />
            </div>
          </div>
          <div className="mt-3 overflow-hidden rounded border bg-card sm:mt-4">
            <div className="grid grid-cols-[1.4fr_1fr_.8fr] gap-1 border-b bg-muted/50 p-1.5 sm:gap-2 sm:p-2">
              {["Transaction", "Match", "Amount"].map((label) => (
                <span key={label} className="text-[7px] text-muted-foreground sm:text-[8px]">
                  {label}
                </span>
              ))}
            </div>
            {["ACME BV · INV-2291", "Figma · INV-2294", "AWS EMEA · INV-2310", "Stripe payout"].map(
              (label, index) => (
                <div
                  key={label}
                  className="grid grid-cols-[1.4fr_1fr_.8fr] gap-1 border-b p-1.5 text-[7px] sm:gap-2 sm:p-2 sm:text-[9px]"
                >
                  <span className="truncate">{label}</span>
                  <span className="truncate text-muted-foreground">Suggested match</span>
                  <span className="text-right font-mono">
                    {["€2,480", "€192", "€816", "€4,102"][index]}
                  </span>
                </div>
              ),
            )}
          </div>
        </div>
      </div>
      <div
        className="pointer-events-none absolute border-2 border-info transition-all duration-300"
        style={step.box}
      >
        <span className="absolute -top-5 left-[-2px] whitespace-nowrap bg-info px-1.5 py-0.5 font-mono text-[9px] text-info-foreground">
          c{step.id + 55} · {step.target}
        </span>
      </div>
    </div>
  );
}

function LiveScreen({ step, runsetId }: { step: RunStep; runsetId?: string | undefined }) {
  const shot = (step.artifacts ?? []).find((file) => /\.(png|jpe?g|webp)$/i.test(file));
  const src = shot && runsetId ? `/artifacts/runs/${runsetId}/${shot}` : null;
  if (!src)
    return (
      <div className="mt-4 flex min-h-[220px] items-center justify-center rounded-md border bg-surface p-6 text-center text-sm leading-6 text-muted-foreground">
        No screenshot for this step — captures are written when the driver returns one.
      </div>
    );
  return (
    <div className="mt-4 overflow-hidden rounded-md border bg-surface">
      <img src={src} alt={`Screenshot for step ${step.id}`} className="w-full" />
      <p className="border-t bg-card px-3 py-2 font-mono text-[10px] text-muted-foreground">
        {shot}
      </p>
    </div>
  );
}
