import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, ChevronDown, Loader2, PlugZap, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, DEMO_MODE, type ApiProbeResult, type ApiProvider } from "@/lib/api";
import { providersQuery } from "@/lib/queries";

/**
 * Settings → Providers & models (P3).
 *
 * Honesty rules this card follows: the live page never shows a mock number (empty state until the
 * list arrives), a key is written once and only its last 4 characters are ever rendered, and
 * "Test connection" shows the REAL result of a real call — including the failure, with the reason.
 */

const KIND_LABEL: Record<ApiProvider["kind"], string> = {
  api_key: "API key",
  oauth_external: "Local subscription",
  local: "Local server",
};

function statusOf(provider: ApiProvider): { text: string; variant: "secondary" | "outline" } {
  if (provider.configured === true)
    return {
      text: provider.kind === "oauth_external" ? "Signed in" : "Configured",
      variant: "secondary",
    };
  if (provider.configured === null) return { text: "Check it", variant: "outline" };
  return { text: "Not set", variant: "outline" };
}

function whereFrom(provider: ApiProvider): string {
  if (provider.kind === "oauth_external") return provider.configured_detail || "local session";
  if (provider.key_source === "store")
    return `stored on this machine${provider.key_last4 ? ` ···${provider.key_last4}` : ""}`;
  if (provider.key_source === "env") return "from the .env file";
  if (provider.kind === "local") return "no key needed";
  return "no key yet";
}

function latency(ms: number | null): string {
  if (ms === null) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

const modelNames = (provider: ApiProvider) => {
  const routine = provider.models?.routine || "";
  const hard = provider.models?.hard || "";
  if (!routine && !hard) return "";
  if (routine === hard) return routine;
  const parts: string[] = [];
  if (routine) parts.push(`routine ${routine}`);
  if (hard) parts.push(`hard ${hard}`);
  return parts.join(" · ");
};

export function ProvidersCard() {
  const queryClient = useQueryClient();
  const providers = useQuery(providersQuery());
  const [openKeyFor, setOpenKeyFor] = useState<string | null>(null);
  const [keyDraft, setKeyDraft] = useState("");
  const [probes, setProbes] = useState<Record<string, ApiProbeResult | "pending">>({});
  const [advancedFor, setAdvancedFor] = useState<string | null>(null);
  const [modelDraft, setModelDraft] = useState<Record<string, { routine: string; hard: string }>>(
    {},
  );

  const draftFor = (provider: ApiProvider) =>
    modelDraft[provider.id] ?? {
      routine: provider.models?.routine ?? "",
      hard: provider.models?.hard ?? "",
    };
  const editDraft = (id: string, patch: Partial<{ routine: string; hard: string }>) =>
    setModelDraft((current) => {
      const base = current[id] ?? { routine: "", hard: "" };
      return { ...current, [id]: { ...base, ...patch } };
    });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["providers"] });

  const saveKey = useMutation({
    mutationFn: (input: { id: string; key: string }) => api.setProviderKey(input.id, input.key),
    onSuccess: async (result) => {
      toast.success(`Key saved · it ends in ${result.key_last4}`);
      setOpenKeyFor(null);
      setKeyDraft("");
      await refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const removeKey = useMutation({
    mutationFn: (id: string) => api.removeProviderKey(id),
    onSuccess: async () => {
      toast.success("Key removed from this machine.");
      await refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const makeDefault = useMutation({
    mutationFn: (id: string) => api.updateProvider(id, { set_default: true }),
    onSuccess: async (_row, id) => {
      toast.success(`${id} is now the provider agents use.`);
      await refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const saveModels = useMutation({
    mutationFn: (input: { id: string; routine: string; hard: string }) =>
      api.updateProvider(input.id, {
        default_models: { routine: input.routine, hard: input.hard },
      }),
    onSuccess: async () => {
      toast.success("Models updated.");
      await refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const test = useMutation({
    mutationFn: (id: string) => api.testProvider(id),
    onMutate: (id) => {
      setProbes((current) => ({ ...current, [id]: "pending" }));
    },
    onSuccess: (result, id) => {
      setProbes((current) => ({ ...current, [id]: result }));
    },
    onError: (error: Error, id) => {
      toast.error(error.message);
      setProbes((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
    },
  });

  if (DEMO_MODE) return null;

  const rows = providers.data ?? [];

  return (
    <Card className="mt-4">
      <CardHeader>
        <h2 className="text-base font-semibold">Providers &amp; models</h2>
        <CardDescription>
          Bring your own key. It is stored on this machine, used for runs, and never shown again —
          not even here.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {providers.isPending && <p className="text-sm text-muted-foreground">Reading providers…</p>}
        {providers.isError && (
          <div className="flex items-center justify-between gap-4 rounded-md border p-3 text-sm">
            <span className="text-muted-foreground">
              Could not read the provider list from the local control plane.
            </span>
            <Button variant="outline" size="sm" onClick={() => void providers.refetch()}>
              Retry
            </Button>
          </div>
        )}
        {!providers.isPending && !providers.isError && rows.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No providers available in this build — nothing to configure.
          </p>
        )}

        {rows.map((provider) => {
          const status = statusOf(provider);
          const probe = probes[provider.id];
          const models = modelNames(provider);
          const canHoldKey = provider.kind === "api_key" && provider.compatible;
          return (
            <div key={provider.id} className="rounded-md border">
              <div className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{provider.label}</span>
                    <Badge variant="outline" className="font-normal text-muted-foreground">
                      {KIND_LABEL[provider.kind]}
                    </Badge>
                    <Badge variant={status.variant} className="font-normal">
                      {status.text}
                    </Badge>
                    {provider.role === "engine" && (
                      <Badge variant="secondary" className="font-normal">
                        Running now
                      </Badge>
                    )}
                    {provider.role === "model" && (
                      <Badge variant="secondary" className="font-normal">
                        Model provider
                      </Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {whereFrom(provider)}
                    {models ? ` — ${models}` : ""}
                  </p>
                  {provider.note && (
                    <p className="mt-1 text-xs text-muted-foreground">{provider.note}</p>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {canHoldKey && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setOpenKeyFor(openKeyFor === provider.id ? null : provider.id);
                        setKeyDraft("");
                      }}
                    >
                      {provider.key_in_store ? "Replace key" : "Paste key"}
                    </Button>
                  )}
                  {provider.key_in_store && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={removeKey.isPending}
                      onClick={() => removeKey.mutate(provider.id)}
                    >
                      Remove
                    </Button>
                  )}
                  {provider.compatible && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={probe === "pending"}
                      onClick={() => test.mutate(provider.id)}
                    >
                      {probe === "pending" ? (
                        <>
                          <Loader2 className="mr-1.5 size-3.5 animate-spin" /> Testing
                        </>
                      ) : (
                        <>
                          <PlugZap className="mr-1.5 size-3.5" /> Test connection
                        </>
                      )}
                    </Button>
                  )}
                  {!provider.is_default && provider.kind !== "oauth_external" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={makeDefault.isPending}
                      onClick={() => makeDefault.mutate(provider.id)}
                    >
                      Use this one
                    </Button>
                  )}
                </div>
              </div>

              {openKeyFor === provider.id && canHoldKey && (
                <div className="border-t p-4">
                  <Label
                    htmlFor={`key-${provider.id}`}
                    className="text-xs uppercase text-muted-foreground"
                  >
                    {provider.label} API key
                  </Label>
                  <div className="mt-1.5 flex gap-2">
                    <Input
                      id={`key-${provider.id}`}
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder="paste the key, then Save"
                      value={keyDraft}
                      onChange={(event) => setKeyDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && keyDraft.trim())
                          saveKey.mutate({ id: provider.id, key: keyDraft.trim() });
                      }}
                    />
                    <Button
                      size="sm"
                      disabled={!keyDraft.trim() || saveKey.isPending}
                      onClick={() => saveKey.mutate({ id: provider.id, key: keyDraft.trim() })}
                    >
                      Save
                    </Button>
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Saved to this machine only. No screen ever reads it back — after saving you will
                    see just its last 4 characters.
                  </p>
                </div>
              )}

              {probe && probe !== "pending" && (
                <div className="border-t px-4 py-3 text-xs">
                  {probe.ok ? (
                    <span className="flex items-center gap-1.5">
                      <CheckCircle2 className="size-3.5 text-emerald-600" />
                      Answered{probe.latency_ms !== null ? ` in ${latency(probe.latency_ms)}` : ""}
                      {probe.model_echo ? ` · ${probe.model_echo}` : ""}
                      {probe.tokens ? ` · ${probe.tokens.toLocaleString()} tokens` : ""}
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5">
                      <XCircle className="size-3.5 text-destructive" />
                      <span className="text-muted-foreground">
                        Failed{probe.status_code ? ` (HTTP ${probe.status_code})` : ""} —{" "}
                        {probe.detail || "no detail reported"}
                      </span>
                    </span>
                  )}
                </div>
              )}

              <Collapsible
                open={advancedFor === provider.id}
                onOpenChange={(open) => setAdvancedFor(open ? provider.id : null)}
              >
                <CollapsibleTrigger className="flex w-full items-center gap-1.5 border-t px-4 py-2 text-xs text-muted-foreground hover:text-foreground">
                  <ChevronDown
                    className={`size-3.5 transition-transform ${advancedFor === provider.id ? "rotate-180" : ""}`}
                  />
                  Advanced — endpoint and models
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="space-y-3 border-t px-4 py-3">
                    <div className="grid gap-1.5 sm:grid-cols-2">
                      <div>
                        <Label
                          htmlFor={`routine-${provider.id}`}
                          className="text-xs uppercase text-muted-foreground"
                        >
                          Routine model
                        </Label>
                        <Input
                          id={`routine-${provider.id}`}
                          value={draftFor(provider).routine}
                          onChange={(event) =>
                            editDraft(provider.id, { routine: event.target.value })
                          }
                          placeholder="model id for routine work"
                          className="mt-1.5 font-mono text-xs"
                        />
                      </div>
                      <div>
                        <Label
                          htmlFor={`hard-${provider.id}`}
                          className="text-xs uppercase text-muted-foreground"
                        >
                          Hard model
                        </Label>
                        <Input
                          id={`hard-${provider.id}`}
                          value={draftFor(provider).hard}
                          onChange={(event) => editDraft(provider.id, { hard: event.target.value })}
                          placeholder="model id for hard work"
                          className="mt-1.5 font-mono text-xs"
                        />
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={saveModels.isPending}
                        onClick={() =>
                          saveModels.mutate({
                            id: provider.id,
                            routine: draftFor(provider).routine.trim(),
                            hard: draftFor(provider).hard.trim(),
                          })
                        }
                      >
                        Save models
                      </Button>
                      <span className="text-xs text-muted-foreground">
                        Used when this provider is the one in use
                        {provider.base_url_source !== "default"
                          ? ` · endpoint from your ${provider.base_url_source} setting`
                          : ""}
                      </span>
                    </div>
                    <p className="break-all font-mono text-[11px] text-muted-foreground">
                      {provider.base_url || "no endpoint (local session)"}
                    </p>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
