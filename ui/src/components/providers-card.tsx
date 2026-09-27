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
import { useT, type MessageKey, type Translate } from "@/lib/i18n";

/**
 * Settings → Providers & models (P3).
 *
 * Honesty rules this card follows: the live page never shows a mock number (empty state until the
 * list arrives), a key is written once and only its last 4 characters are ever rendered, and
 * "Test connection" shows the REAL result of a real call — including the failure, with the reason.
 */

const KIND_LABEL: Record<ApiProvider["kind"], MessageKey> = {
  api_key: "prov.kindApiKey",
  oauth_external: "prov.kindSubscription",
  local: "prov.kindLocal",
};

function statusOf(
  provider: ApiProvider,
  t: Translate,
): { text: string; variant: "secondary" | "outline" } {
  if (provider.configured === true)
    return {
      text: provider.kind === "oauth_external" ? t("prov.signedIn") : t("prov.configured"),
      variant: "secondary",
    };
  if (provider.configured === null) return { text: t("prov.checkIt"), variant: "outline" };
  return { text: t("prov.notSet"), variant: "outline" };
}

/** Notes/details come from the local service in English; show the known ones translated. */
const SERVER_TEXT: Record<string, MessageKey> = {
  "measured here 2026-09-23 (Luna routine / Sol hard)": "prov.srv.measured",
  "no model default shipped — set a model before probing": "prov.srv.noModel",
  "no key needed — start the server and run Test connection": "prov.srv.startServer",
  "native Messages API — the llm brain speaks chat-completions; not wired yet": "prov.srv.native",
  "the local Codex CLI session (~/.codex/auth.json); no API key; local-only": "prov.srv.codexSession",
  "key stored locally": "prov.srv.keyStored",
  "key from the environment (.env)": "prov.srv.keyEnv",
  "no key yet — add one to use this provider": "prov.srv.noKey",
  "cli missing or no login — run `codex login`": "prov.srv.cliMissing",
  "no key needed — run Test connection": "prov.srv.noKeyTest",
};

function serverText(text: string, t: Translate): string {
  const key = SERVER_TEXT[text];
  if (key) return t(key);
  const found = /^cli found · session present \((.*)\)$/.exec(text);
  return found ? t("prov.srv.cliFound", { home: found[1] ?? "" }) : text;
}

function whereFrom(provider: ApiProvider, t: Translate): string {
  if (provider.kind === "oauth_external")
    return provider.configured_detail
      ? serverText(provider.configured_detail, t)
      : t("prov.localSession");
  if (provider.key_source === "store")
    return `${t("prov.stored")}${provider.key_last4 ? ` ···${provider.key_last4}` : ""}`;
  if (provider.key_source === "env") return t("prov.fromEnv");
  if (provider.kind === "local") return t("prov.noKeyNeeded");
  return t("prov.noKeyYet");
}

function latency(ms: number | null): string {
  if (ms === null) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

const modelNames = (provider: ApiProvider, t: Translate) => {
  const routine = provider.models?.routine || "";
  const hard = provider.models?.hard || "";
  if (!routine && !hard) return "";
  if (routine === hard) return routine;
  const parts: string[] = [];
  if (routine) parts.push(t("prov.routineModelShort", { model: routine }));
  if (hard) parts.push(t("prov.hardModelShort", { model: hard }));
  return parts.join(" · ");
};

export function ProvidersCard() {
  const t = useT();
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
      toast.success(t("prov.keySaved", { last4: result.key_last4 }));
      setOpenKeyFor(null);
      setKeyDraft("");
      await refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const removeKey = useMutation({
    mutationFn: (id: string) => api.removeProviderKey(id),
    onSuccess: async () => {
      toast.success(t("prov.keyRemoved"));
      await refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const makeDefault = useMutation({
    mutationFn: (id: string) => api.updateProvider(id, { set_default: true }),
    onSuccess: async (_row, id) => {
      toast.success(t("prov.nowDefault", { id }));
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
      toast.success(t("prov.modelsUpdated"));
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
        <h2 className="text-base font-semibold">{t("prov.title")}</h2>
        <CardDescription>{t("prov.intro")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {providers.isPending && (
          <p className="text-sm text-muted-foreground">{t("prov.reading")}</p>
        )}
        {providers.isError && (
          <div className="flex items-center justify-between gap-4 rounded-md border p-3 text-sm">
            <span className="text-muted-foreground">{t("prov.loadError")}</span>
            <Button variant="outline" size="sm" onClick={() => void providers.refetch()}>
              {t("prov.retry")}
            </Button>
          </div>
        )}
        {!providers.isPending && !providers.isError && rows.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("prov.none")}</p>
        )}

        {rows.map((provider) => {
          const status = statusOf(provider, t);
          const probe = probes[provider.id];
          const models = modelNames(provider, t);
          const canHoldKey = provider.kind === "api_key" && provider.compatible;
          return (
            <div key={provider.id} className="rounded-md border">
              <div className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{provider.label}</span>
                    <Badge variant="outline" className="font-normal text-muted-foreground">
                      {t(KIND_LABEL[provider.kind])}
                    </Badge>
                    <Badge variant={status.variant} className="font-normal">
                      {status.text}
                    </Badge>
                    {provider.role === "engine" && (
                      <Badge variant="secondary" className="font-normal">
                        {t("prov.runningNow")}
                      </Badge>
                    )}
                    {provider.role === "model" && (
                      <Badge variant="secondary" className="font-normal">
                        {t("prov.modelProvider")}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {whereFrom(provider, t)}
                    {models ? ` — ${models}` : ""}
                  </p>
                  {provider.note && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {serverText(provider.note, t)}
                    </p>
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
                      {provider.key_in_store ? t("prov.replaceKey") : t("prov.pasteKey")}
                    </Button>
                  )}
                  {provider.key_in_store && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={removeKey.isPending}
                      onClick={() => removeKey.mutate(provider.id)}
                    >
                      {t("m.remove")}
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
                          <Loader2 className="mr-1.5 size-3.5 animate-spin" /> {t("prov.testing")}
                        </>
                      ) : (
                        <>
                          <PlugZap className="mr-1.5 size-3.5" /> {t("prov.testConn")}
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
                      {t("prov.useThis")}
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
                    {t("prov.keyLabel", { provider: provider.label })}
                  </Label>
                  <div className="mt-1.5 flex gap-2">
                    <Input
                      id={`key-${provider.id}`}
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={t("prov.keyPlaceholder")}
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
                      {t("m.save")}
                    </Button>
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">{t("prov.keyHint")}</p>
                </div>
              )}

              {probe && probe !== "pending" && (
                <div className="border-t px-4 py-3 text-xs">
                  {probe.ok ? (
                    <span className="flex items-center gap-1.5">
                      <CheckCircle2 className="size-3.5 text-emerald-600" />
                      {probe.latency_ms !== null
                        ? t("prov.answeredIn", { time: latency(probe.latency_ms) })
                        : t("prov.answered")}
                      {probe.model_echo ? ` · ${probe.model_echo}` : ""}
                      {probe.tokens
                        ? ` · ${t("prov.tokens", { n: probe.tokens.toLocaleString() })}`
                        : ""}
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5">
                      <XCircle className="size-3.5 text-destructive" />
                      <span className="text-muted-foreground">
                        {t("prov.failed")}
                        {probe.status_code ? ` (HTTP ${probe.status_code})` : ""} —{" "}
                        {probe.detail || t("prov.noDetail")}
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
                  {t("prov.advanced")}
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="space-y-3 border-t px-4 py-3">
                    <div className="grid gap-1.5 sm:grid-cols-2">
                      <div>
                        <Label
                          htmlFor={`routine-${provider.id}`}
                          className="text-xs uppercase text-muted-foreground"
                        >
                          {t("prov.routineModel")}
                        </Label>
                        <Input
                          id={`routine-${provider.id}`}
                          value={draftFor(provider).routine}
                          onChange={(event) =>
                            editDraft(provider.id, { routine: event.target.value })
                          }
                          placeholder={t("prov.routinePlaceholder")}
                          className="mt-1.5 font-mono text-xs"
                        />
                      </div>
                      <div>
                        <Label
                          htmlFor={`hard-${provider.id}`}
                          className="text-xs uppercase text-muted-foreground"
                        >
                          {t("prov.hardModel")}
                        </Label>
                        <Input
                          id={`hard-${provider.id}`}
                          value={draftFor(provider).hard}
                          onChange={(event) => editDraft(provider.id, { hard: event.target.value })}
                          placeholder={t("prov.hardPlaceholder")}
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
                        {t("prov.saveModels")}
                      </Button>
                      <span className="text-xs text-muted-foreground">
                        {t("prov.usedWhen")}
                        {provider.base_url_source !== "default"
                          ? ` · ${t("prov.endpointFrom", { source: provider.base_url_source })}`
                          : ""}
                      </span>
                    </div>
                    <p className="break-all font-mono text-[11px] text-muted-foreground">
                      {provider.base_url || t("prov.noEndpoint")}
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
