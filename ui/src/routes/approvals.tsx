import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, ShieldCheck, Trash2, X } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { ErrorState, RefreshButton, RowSkeleton } from "@/components/data-state";
import { approvalQueueQuery, agentsQuery, grantsQuery } from "@/lib/queries";
import { MissionApprovalPreview, missionIdFromApprovalTitle } from "@/components/mission-preview";
import { useT, type MessageKey } from "@/lib/i18n";
import { api, type ApprovalDecisionRequest, type ApiApprovalQueueItem } from "@/lib/api";

export const Route = createFileRoute("/approvals")({
  head: () => ({ meta: [{ title: "Approvals — Eeze Agents" }] }),
  component: ApprovalsPage,
});

const riskStyles: Record<string, string> = {
  read: "bg-success/12 text-success border-success/25",
  write_local: "bg-warning/15 text-warning border-warning/30",
  external_send: "bg-orange/15 text-orange border-orange/30",
  install_exec: "bg-info/12 text-info border-info/25",
  destructive: "bg-destructive/12 text-destructive border-destructive/30",
  system: "bg-info/12 text-info border-info/25",
};

const riskLabels: Record<string, string> = {
  read: "Read",
  write_local: "Write (local)",
  external_send: "Send",
  install_exec: "Runs a program",
  destructive: "Destructive",
  system: "System",
};

function RiskPill({ risk }: { risk: string }) {
  const t = useT();
  const key = `risk.${risk}` as MessageKey;
  const label = t(key) === key ? (riskLabels[risk] ?? risk) : t(key);
  return (
    <Badge
      variant="outline"
      className={`font-medium ${riskStyles[risk] ?? "bg-muted text-muted-foreground"}`}
    >
      {label}
    </Badge>
  );
}

const statusStyles: Record<string, string> = {
  approved: "bg-success/12 text-success border-success/25",
  denied: "bg-destructive/12 text-destructive border-destructive/30",
  abandoned: "bg-muted text-muted-foreground",
  expired: "bg-muted text-muted-foreground",
};

function ApprovalsPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const pending = useQuery(approvalQueueQuery("pending"));
  const all = useQuery(approvalQueueQuery(undefined));
  const grants = useQuery(grantsQuery());
  const agents = useQuery(agentsQuery());
  const [grantOn, setGrantOn] = useState<Record<string, boolean>>({});
  const agentName = (id: string) => agents.data?.find((agent) => agent.id === id)?.name ?? id;

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["approval-queue"] }),
      queryClient.invalidateQueries({ queryKey: ["grants"] }),
      queryClient.invalidateQueries({ queryKey: ["approvals"] }),
      queryClient.invalidateQueries({ queryKey: ["system-status"] }),
    ]);
  };

  const decide = useMutation({
    mutationFn: ({ id, body }: { id: string; body: ApprovalDecisionRequest }) =>
      api.decideApproval(id, body),
    onSuccess: async (result, variables) => {
      if (variables.body.decision === "abandon") {
        toast.info(t("a.toast.dismissed"));
      } else if (variables.body.decision === "deny") {
        toast.info(t("a.toast.denied"));
      } else if (result.resumed) {
        toast.success(t("a.toast.resuming"));
      } else {
        toast.success(t("a.toast.approved"));
      }
      await invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.revokeGrant(id),
    onSuccess: async () => {
      toast.success(t("a.toast.revoked"));
      await invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const items = pending.data ?? [];
  const decided = (all.data ?? []).filter((item) => item.status !== "pending").slice(0, 8);
  const activeGrants = (grants.data ?? []).filter((grant) => grant.status === "active");
  const busy = decide.isPending;

  const onDismiss = (item: ApiApprovalQueueItem) => {
    decide.mutate({ id: item.id, body: { decision: "abandon", auto_resume: false } });
  };

  const onDecide = (item: ApiApprovalQueueItem, decision: "approve" | "deny") => {
    if (!item.resumable) return;
    const withGrant = decision === "approve" && grantOn[item.id];
    decide.mutate({
      id: item.id,
      body: {
        decision,
        auto_resume: decision === "approve",
        ...(withGrant ? { grant: { scope: "task" as const, ttl_hours: 24 } } : {}),
      },
    });
  };

  return (
    <>
      <AppHeader />
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{t("a.title")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t("a.intro")}</p>
          </div>
          <RefreshButton onRefresh={() => void pending.refetch()} refreshing={pending.isFetching} />
        </div>

        {pending.isError && (
          <div className="mt-6">
            <ErrorState
              message={t("a.loadError")}
              detail={t("a.loadErrorHint")}
              onRetry={() => void pending.refetch()}
            />
          </div>
        )}

        {pending.isPending && <RowSkeleton />}

        <div className={`mt-6 space-y-4 ${pending.isPending ? "hidden" : ""}`}>
          {items.map((item) => (
            <Card key={item.id}>
              <CardHeader className="flex flex-row items-start gap-3 space-y-0">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-base font-semibold tracking-tight">{item.title}</h2>
                    <Badge variant="outline" className="font-medium">
                      {agentName(item.agent_id)}
                    </Badge>
                    <RiskPill risk={item.risk_class} />
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    run <span className="font-mono text-xs">{item.run_id}</span> · step{" "}
                    <span className="font-mono text-xs">{item.step_id}</span> ·{" "}
                    {item.requested_at ?? "just now"}
                  </p>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {missionIdFromApprovalTitle(item.title) && (
                  <MissionApprovalPreview missionId={missionIdFromApprovalTitle(item.title) ?? ""} />
                )}
                <details open={!missionIdFromApprovalTitle(item.title)}>
                  <summary className="cursor-pointer text-xs text-muted-foreground">
                    {t("a.tech")}
                  </summary>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-md border border-border bg-muted/60 p-3 font-mono text-xs text-foreground">
                    {JSON.stringify(item.payload_preview, null, 2)}
                  </pre>
                </details>
                {item.resumable && item.risk_class === "destructive" ? (
                  <p className="text-sm text-muted-foreground">{t("a.noGrant")}</p>
                ) : item.resumable ? (
                  <label className="flex items-center gap-2 text-sm text-muted-foreground">
                    <input
                      type="checkbox"
                      className="size-4 accent-[var(--primary)]"
                      checked={Boolean(grantOn[item.id])}
                      onChange={(event) =>
                        setGrantOn((current) => ({ ...current, [item.id]: event.target.checked }))
                      }
                    />
                    {missionIdFromApprovalTitle(item.title)
                      ? t("a.grantMission")
                      : t("a.grantTask")}
                  </label>
                ) : (
                  <p role="status" className="text-sm text-warning">
                    {t("a.legacy")}
                  </p>
                )}
              </CardContent>
              {!item.resumable && (
                <CardFooter className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => onDismiss(item)}
                  >
                    <Trash2 className="size-4" /> {t("a.dismiss")}
                  </Button>
                </CardFooter>
              )}
              {item.resumable && (
                <CardFooter className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={busy} onClick={() => onDecide(item, "approve")}>
                    <Check className="size-4" /> {t("a.approve")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => onDecide(item, "deny")}
                  >
                    <X className="size-4" /> {t("a.deny")}
                  </Button>
                </CardFooter>
              )}
            </Card>
          ))}

          {!pending.isPending && !pending.isError && items.length === 0 && (
            <div className="rounded-lg border border-dashed border-border py-16 text-center">
              <ShieldCheck className="mx-auto size-6 text-muted-foreground" />
              <p className="mt-2 text-sm font-medium">{t("a.empty")}</p>
              <p className="mt-1 text-sm text-muted-foreground">{t("a.emptyHint")}</p>
            </div>
          )}
        </div>

        {decided.length > 0 && (
          <section className="mt-10">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              {t("a.recent")}
            </h2>
            <div className="mt-3 divide-y rounded-lg border border-border">
              {decided.map((item) => (
                <div key={item.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
                  <Badge
                    variant="outline"
                    className={`font-medium ${statusStyles[item.status] ?? ""}`}
                  >
                    {t(`status.${item.status}` as MessageKey) === `status.${item.status}`
                      ? item.status
                      : t(`status.${item.status}` as MessageKey)}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate text-sm">{item.title}</span>
                  <Badge variant="outline" className="font-medium">
                    {agentName(item.agent_id)}
                  </Badge>
                  <RiskPill risk={item.risk_class} />
                </div>
              ))}
            </div>
          </section>
        )}

        {activeGrants.length > 0 && (
          <section className="mt-10">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              {t("a.grants")}
            </h2>
            <div className="mt-3 divide-y rounded-lg border border-border">
              {activeGrants.map((grant) => (
                <div key={grant.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
                  <span className="min-w-0 flex-1 truncate text-sm">
                    <span className="font-medium">{grant.risk_class}</span>{" "}
                    {grant.scope === "task"
                      ? t("a.forTask", { task: grant.task ?? "" })
                      : t("a.forAgent")}{" "}
                    <span className="text-muted-foreground">
                      {grant.expires_at ? t("a.expires", { at: grant.expires_at }) : t("a.noExpiry")}
                    </span>
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(grant.id)}
                  >
                    <Trash2 className="size-4" /> {t("a.revoke")}
                  </Button>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
