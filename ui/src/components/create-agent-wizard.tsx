import { useMemo, useState, type CSSProperties } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Bug, FileText, Mail, Search, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { AgentAvatar } from "@/components/agent-avatar";
import { useStore } from "@/components/app-store";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { DEMO_MODE, api, type AgentCreateRequest } from "@/lib/api";
import type { Agent } from "@/lib/mock-data";

const permissions = [
  ["browser", "Browser control", "Open pages and interact with websites."],
  ["files", "Local files", "Read and update files you select."],
  ["email", "Send email", "Draft and send messages from connected accounts."],
  ["calendar", "Calendar", "Read events and manage your schedule."],
  ["payments", "Payments", "Prepare and submit financial transactions."],
  ["terminal", "Terminal", "Run approved commands on your computer."],
] as const;

/** UI grants → runtime risk classes (a grant can map to several). */
const GRANT_TO_RISK: Record<string, string[]> = {
  browser: ["read"],
  files: ["read", "write_local"],
  email: ["external_send"],
  calendar: ["read", "write_local"],
  payments: ["destructive"],
  terminal: ["install_exec"],
};

const templates = [
  {
    id: "fin",
    name: "Fin",
    role: "Accounting & Finance",
    description: "Reconcile invoices, expenses, and cash flow.",
    accent: "emerald",
    icon: BookOpen,
    grants: ["browser", "files", "email"],
  },
  {
    id: "inbox",
    name: "Inbox",
    role: "Email & Scheduling",
    description: "Triage messages and protect your calendar.",
    accent: "violet",
    icon: Mail,
    grants: ["browser", "email", "calendar"],
  },
  {
    id: "scout",
    name: "Scout",
    role: "Research & Monitoring",
    description: "Track sources, competitors, and changes.",
    accent: "amber",
    icon: Search,
    grants: ["browser", "files"],
  },
  {
    id: "scribe",
    name: "Scribe",
    role: "Documents & Forms",
    description: "Draft documents and complete repetitive forms.",
    accent: "sky",
    icon: FileText,
    grants: ["browser", "files"],
  },
  {
    id: "qa",
    name: "QA",
    role: "Testing & Verification",
    description: "Check workflows and report clear failures.",
    accent: "rose",
    icon: Bug,
    grants: ["browser", "terminal"],
  },
  {
    id: "custom",
    name: "Custom",
    role: "Start from scratch",
    description: "Build a focused agent for your own workflow.",
    accent: "slate",
    icon: Sparkles,
    grants: [],
  },
] as const;

const colors = ["emerald", "violet", "amber", "sky", "rose", "slate", "blue", "lime"];
const autonomyOptions = [
  ["suggest", "Always ask", "Approve every action"],
  ["approve", "Ask on risk", "Auto-execute read/write, ask for send/pay (Recommended)"],
  ["autonomous", "Fully autonomous", "Execute everything within budget"],
] as const;

export function CreateAgentWizard({
  open,
  onOpenChange,
  editAgent = null,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editAgent?: Agent | null;
}) {
  const { agents, addAgent } = useStore();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState(1);
  const [templateId, setTemplateId] = useState("fin");
  const template = templates.find((item) => item.id === templateId) ?? templates[0];
  const [name, setName] = useState("Fin 2.0");
  const [description, setDescription] = useState<string>(template.description);
  const [accent, setAccent] = useState(template.accent as string);
  const [grants, setGrants] = useState<string[]>([...template.grants]);
  const [autonomy, setAutonomy] = useState<Agent["autonomy"]>("approve");
  const [brain, setBrain] = useState<"jev" | "llm">("jev");

  const selectedPermissions = useMemo(
    () => permissions.filter(([id]) => grants.includes(id)),
    [grants],
  );
  const chooseTemplate = (id: string) => {
    const next = templates.find((item) => item.id === id) ?? templates[0];
    setTemplateId(next.id);
    setName(next.id === "custom" ? "My Agent" : `${next.name} 2.0`);
    setDescription(next.description);
    setAccent(next.accent);
    setGrants([...next.grants]);
  };
  const close = () => {
    onOpenChange(false);
    setStep(1);
  };
  const createReal = useMutation({
    mutationFn: (payload: AgentCreateRequest) => api.createAgent(payload),
    onSuccess: async (agent) => {
      toast.success(
        editAgent
          ? `${agent.name} updated.`
          : `${agent.name} is ready — pick it in the agent selector.`,
      );
      await queryClient.invalidateQueries({ queryKey: ["agents"] });
      close();
      if (!editAgent) void navigate({ to: "/demo" });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const create = () => {
    const displayName = name.trim() || "New Agent";
    if (!DEMO_MODE) {
      const slug =
        displayName
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-|-$/g, "") || "agent";
      const riskClasses = new Set<string>(["read"]);
      if (autonomy !== "suggest") {
        grants.forEach((grant) =>
          (GRANT_TO_RISK[grant] ?? []).forEach((cls) => riskClasses.add(cls)),
        );
      }
      createReal.mutate({
        id: slug,
        name: displayName,
        role: template.role === "Start from scratch" ? "custom" : template.role,
        permissions: { risk_classes: [...riskClasses], apps: ["*"], allow_foreground: false },
        model: { brain },
      });
      return;
    }
    const id = `${
      name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || "agent"
    }-${Date.now()}`;
    addAgent({
      id,
      name: name.trim() || "New Agent",
      role: template.role === "Start from scratch" ? "Custom workflow" : template.role,
      accent,
      status: "idle",
      metrics: { tasksToday: 0, successRate: 1, costToday: 0, timeSaved: "0h" },
      description,
      personality: "Calm, precise, and transparent about every decision.",
      model: "claude-sonnet-4.6",
      plannerModel: "jev-planner-2",
      autonomy,
      dailyBudget: 10,
      permissions: permissions.map(([permissionId, label]) => ({
        id: permissionId,
        label,
        granted: grants.includes(permissionId),
      })),
      tools: [],
      routines: [],
      memory: [],
      history: [],
      createdAt: "Today",
    });
    close();
    void navigate({ to: "/demo" });
    toast.success(
      `${name.trim() || "New Agent"} is ready — try asking it to reconcile your first invoice`,
    );
  };

  return (
    <Dialog open={open} onOpenChange={(value) => (value ? onOpenChange(true) : close())}>
      <DialogContent className="flex max-h-[90vh] w-[calc(100%-2rem)] max-w-3xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-5 pr-12">
          {!editAgent && (
            <div className="mb-3 flex gap-1.5" aria-label={`Step ${step} of 5`}>
              {[1, 2, 3, 4, 5].map((number) => (
                <span
                  key={number}
                  className={cn(
                    "h-1.5 flex-1 rounded-full bg-muted",
                    number <= step && "bg-primary",
                  )}
                />
              ))}
            </div>
          )}
          <DialogTitle>
            {editAgent
              ? `Edit ${editAgent.name}`
              : [
                  "Choose a template",
                  "Personalize",
                  "Permissions",
                  "Autonomy level",
                  "Review & create",
                ][step - 1]}
          </DialogTitle>
          <DialogDescription>
            {editAgent
              ? editAgent.source === "repo"
                ? "This is a built-in agent — saving creates a user-level override (~/.eeze/agents.yaml)."
                : "Saved to your user file (~/.eeze/agents.yaml)."
              : `Step ${step} of 5`}
          </DialogDescription>
        </DialogHeader>

        {editAgent ? (
          <EditAgentForm
            key={editAgent.id}
            agent={editAgent}
            saving={createReal.isPending}
            onSave={(payload) => createReal.mutate(payload)}
            onCancel={close}
          />
        ) : (
          <>
            <div className="min-h-0 flex-1 overflow-y-auto p-6">
              {step === 1 && (
                <div className="grid gap-3 sm:grid-cols-2">
                  {templates.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => chooseTemplate(item.id)}
                        className={cn(
                          "flex min-h-28 items-start gap-3 rounded-md border p-4 text-left transition-colors hover:bg-accent",
                          templateId === item.id && "border-primary bg-accent",
                        )}
                      >
                        <span
                          className="agent-tint grid size-10 shrink-0 place-items-center rounded-full"
                          style={
                            { "--agent-color": `var(--agent-${item.accent})` } as CSSProperties
                          }
                        >
                          <Icon className="size-4" />
                        </span>
                        <span>
                          <span className="block font-medium">{item.name}</span>
                          <span className="block text-xs text-muted-foreground">{item.role}</span>
                          <span className="mt-2 block text-sm text-muted-foreground">
                            {item.description}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {step === 2 && (
                <div className="mx-auto max-w-xl space-y-5">
                  <div className="flex items-center gap-4">
                    <AgentAvatar name={name || "A"} accent={accent} size="lg" />
                    <div>
                      <p className="font-medium">Agent identity</p>
                      <p className="text-sm text-muted-foreground">
                        Choose a name and identity color.
                      </p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="agent-name">Name</Label>
                    <Input
                      id="agent-name"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Avatar color</Label>
                    <div className="flex flex-wrap gap-2">
                      {colors.map((color) => (
                        <button
                          key={color}
                          type="button"
                          aria-label={`${color} avatar`}
                          onClick={() => setAccent(color)}
                          className={cn(
                            "agent-swatch size-8 rounded-full ring-offset-2 ring-offset-background",
                            accent === color && "ring-2 ring-primary",
                          )}
                          style={{ "--agent-color": `var(--agent-${color})` } as CSSProperties}
                        />
                      ))}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="agent-description">Role description</Label>
                    <Textarea
                      id="agent-description"
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      className="min-h-24 resize-none"
                    />
                  </div>
                </div>
              )}

              {step === 3 && (
                <div className="mx-auto max-w-xl divide-y rounded-md border">
                  {permissions.map(([id, label, detail]) => (
                    <div key={id} className="flex items-center gap-4 p-4">
                      <div className="min-w-0 flex-1">
                        <Label htmlFor={`wizard-${id}`}>{label}</Label>
                        <p className="mt-0.5 text-sm text-muted-foreground">{detail}</p>
                      </div>
                      <Switch
                        id={`wizard-${id}`}
                        checked={grants.includes(id)}
                        onCheckedChange={(checked) =>
                          setGrants((current) =>
                            checked ? [...current, id] : current.filter((item) => item !== id),
                          )
                        }
                      />
                    </div>
                  ))}
                </div>
              )}

              {step === 4 && (
                <RadioGroup
                  value={autonomy}
                  onValueChange={(value) => setAutonomy(value as Agent["autonomy"])}
                  className="mx-auto max-w-xl gap-3"
                >
                  {autonomyOptions.map(([value, label, detail]) => (
                    <Label
                      key={value}
                      htmlFor={`autonomy-${value}`}
                      className={cn(
                        "flex cursor-pointer items-start gap-3 rounded-md border p-4 font-normal",
                        autonomy === value && "border-primary bg-accent",
                      )}
                    >
                      <RadioGroupItem id={`autonomy-${value}`} value={value} className="mt-0.5" />
                      <span>
                        <span className="block font-medium">{label}</span>
                        <span className="mt-1 block text-sm text-muted-foreground">{detail}</span>
                      </span>
                    </Label>
                  ))}
                </RadioGroup>
              )}

              {step === 5 && (
                <div className="mx-auto grid max-w-xl gap-3 sm:grid-cols-2">
                  <div className="rounded-md border p-4 sm:col-span-2">
                    <div className="flex items-center gap-3">
                      <AgentAvatar name={name || "A"} accent={accent} />
                      <div>
                        <p className="font-medium">{name || "New Agent"}</p>
                        <p className="text-sm text-muted-foreground">{template.role}</p>
                      </div>
                    </div>
                    <p className="mt-3 text-sm text-muted-foreground">{description}</p>
                  </div>
                  <div className="rounded-md border p-4">
                    <p className="text-xs font-medium uppercase text-muted-foreground">
                      Permissions
                    </p>
                    <p className="mt-2 text-sm">
                      {selectedPermissions.length
                        ? selectedPermissions.map(([, label]) => label).join(", ")
                        : "None"}
                    </p>
                  </div>
                  <div className="rounded-md border p-4">
                    <p className="text-xs font-medium uppercase text-muted-foreground">Autonomy</p>
                    <p className="mt-2 text-sm">
                      {autonomyOptions.find(([value]) => value === autonomy)?.[1]}
                    </p>
                  </div>
                  <div className="rounded-md border p-4">
                    <p className="text-xs font-medium uppercase text-muted-foreground">
                      Tactical brain
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant={brain === "jev" ? "default" : "outline"}
                        onClick={() => setBrain("jev")}
                      >
                        Jev · fast
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant={brain === "llm" ? "default" : "outline"}
                        onClick={() => setBrain("llm")}
                      >
                        LLM · flexible
                      </Button>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Same judgments, swappable engine. Risky steps stay gated either way.
                    </p>
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between border-t bg-background px-6 py-4">
              <Button
                variant="outline"
                onClick={() => (step === 1 ? close() : setStep((current) => current - 1))}
              >
                {step === 1 ? "Cancel" : "Back"}
              </Button>
              <Button
                onClick={() => (step === 5 ? create() : setStep((current) => current + 1))}
                disabled={(step === 2 && !name.trim()) || createReal.isPending}
              >
                {step === 5 ? (createReal.isPending ? "Creating…" : "Create Agent") : "Next"}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

const RISK_CHOICES: { id: string; label: string; hint: string }[] = [
  { id: "read", label: "Read", hint: "Look at the screen and files — always on." },
  {
    id: "write_local",
    label: "Write local",
    hint: "Type, save and change things on this computer.",
  },
  {
    id: "external_send",
    label: "Send externally",
    hint: "Email or messages outside this computer. Each risky step waits for your click.",
  },
  {
    id: "install_exec",
    label: "Install / run",
    hint: "Install software and run programs. Each risky step waits for your click.",
  },
  {
    id: "destructive",
    label: "Destructive",
    hint: "Delete or overwrite data. Each risky step waits for your click.",
  },
  {
    id: "system",
    label: "System",
    hint: "Change system settings. Each risky step waits for your click.",
  },
];

function EditAgentForm({
  agent,
  saving,
  onSave,
  onCancel,
}: {
  agent: Agent;
  saving: boolean;
  onSave: (payload: AgentCreateRequest) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(agent.name);
  const [role, setRole] = useState(agent.role);
  const [description, setDescription] = useState(agent.description ?? "");
  const [risk, setRisk] = useState<Set<string>>(
    () =>
      new Set(
        agent.permissions
          .filter((p) => p.granted && RISK_CHOICES.some((choice) => choice.id === p.id))
          .map((p) => p.id),
      ),
  );
  const [brain, setBrain] = useState<"jev" | "llm">(agent.model === "llm" ? "llm" : "jev");

  const toggle = (id: string) =>
    setRisk((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      next.add("read"); // read is the floor: without it the agent can do nothing
      return next;
    });

  return (
    <>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="edit-name">Name</Label>
            <Input id="edit-name" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-role">Role</Label>
            <Input
              id="edit-role"
              value={role}
              placeholder="generalist"
              onChange={(event) => setRole(event.target.value)}
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="edit-description">Role description</Label>
          <Textarea
            id="edit-description"
            value={description}
            placeholder="What this agent handles, in one or two sentences."
            className="min-h-20 resize-none"
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div>
          <p className="text-xs font-medium uppercase text-muted-foreground">
            Permissions (risk classes)
          </p>
          <div className="mt-2 divide-y rounded-md border">
            {RISK_CHOICES.map((choice) => (
              <div key={choice.id} className="flex items-center justify-between gap-4 p-3.5">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{choice.label}</p>
                  <p className="text-xs text-muted-foreground">{choice.hint}</p>
                </div>
                <Switch
                  checked={risk.has(choice.id)}
                  disabled={choice.id === "read"}
                  aria-label={choice.label}
                  onCheckedChange={() => toggle(choice.id)}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-md border p-4">
          <p className="text-xs font-medium uppercase text-muted-foreground">Tactical brain</p>
          <div className="mt-2 flex gap-2">
            <Button
              type="button"
              size="sm"
              variant={brain === "jev" ? "default" : "outline"}
              onClick={() => setBrain("jev")}
            >
              Jev · fast
            </Button>
            <Button
              type="button"
              size="sm"
              variant={brain === "llm" ? "default" : "outline"}
              onClick={() => setBrain("llm")}
            >
              LLM · flexible
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Same judgments, swappable engine. Risky steps stay gated either way.
          </p>
        </div>
      </div>
      <div className="flex items-center justify-between border-t bg-background px-6 py-4">
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          disabled={!name.trim() || saving}
          onClick={() =>
            onSave({
              id: agent.id,
              name: name.trim(),
              role: role.trim() || "generalist",
              ...(description.trim() ? { description: description.trim() } : {}),
              permissions: {
                risk_classes: [...new Set([...risk, "read"])],
                apps: ["*"],
                allow_foreground: false,
              },
              model: { brain },
            })
          }
        >
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </>
  );
}
