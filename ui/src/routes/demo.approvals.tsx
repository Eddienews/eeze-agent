import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, HelpCircle, Pencil, X } from "lucide-react";
import { ErrorState, RefreshButton, RowSkeleton } from "@/components/data-state";
import { agentsQuery, approvalsQuery } from "@/lib/queries";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AgentAvatar } from "@/components/agent-avatar";
import { RiskBadge } from "@/components/status-badge";
import { useStore } from "@/components/app-store";
import { type RiskLevel } from "@/lib/mock-data";
import { useT, type MessageKey } from "@/lib/i18n";

export const Route = createFileRoute("/demo/approvals")({
  head: () => ({
    meta: [
      { title: "Approval Inbox — Eeze Agents" },
      {
        name: "description",
        content: "Review and approve every sensitive action your agents want to take.",
      },
      { property: "og:title", content: "Approval Inbox — Eeze Agents" },
      {
        property: "og:description",
        content: "Approve, edit or reject pending agent actions with full context.",
      },
    ],
  }),
  component: ApprovalInbox,
});

const risks: (RiskLevel | "all")[] = ["all", "read", "write", "send", "pay"];

const riskKey: Record<RiskLevel, MessageKey> = {
  read: "risk.read",
  write: "da.risk.write",
  send: "risk.external_send",
  pay: "da.risk.pay",
  exec: "da.risk.exec",
};

function ApprovalInbox() {
  const t = useT();
  const { approvals: localApprovals, agents: localAgents, resolveApproval } = useStore();
  const [agentFilter, setAgentFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState<RiskLevel | "all">("all");
  const [resolved, setResolved] = useState<string[]>([]);

  const approvalsResult = useQuery(approvalsQuery());
  const agentsResult = useQuery(agentsQuery());
  const agents = agentsResult.data ?? localAgents;
  const approvals = (approvalsResult.data ?? localApprovals).filter(
    (item) => !resolved.includes(item.id),
  );

  const visible = useMemo(
    () =>
      approvals.filter(
        (a) =>
          (agentFilter === "all" || a.agentId === agentFilter) &&
          (riskFilter === "all" || a.risk === riskFilter),
      ),
    [approvals, agentFilter, riskFilter],
  );

  const act = (id: string, label: string) => {
    resolveApproval(id);
    setResolved((list) => [...list, id]);
    toast.success(t("da.resolved", { label }));
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("da.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t(approvals.length === 1 ? "da.waitingOne" : "da.waitingMany", {
              n: approvals.length,
            })}
          </p>
        </div>
        <RefreshButton
          onRefresh={() => void approvalsResult.refetch()}
          refreshing={approvalsResult.isFetching}
        />
      </div>
      {approvalsResult.isError && (
        <ErrorState
          message={t("da.loadError")}
          detail={t("team.sampleData")}
          onRetry={() => void approvalsResult.refetch()}
        />
      )}

      <div className="mt-6 flex flex-wrap gap-2">
        <Select value={agentFilter} onValueChange={setAgentFilter}>
          <SelectTrigger className="w-full sm:w-48" aria-label={t("da.filterAgent")}>
            <SelectValue placeholder={t("da.allAgents")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("da.allAgents")}</SelectItem>
            {agents.map((a) => (
              <SelectItem key={a.id} value={a.id}>
                {a.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={riskFilter} onValueChange={(v) => setRiskFilter(v as RiskLevel | "all")}>
          <SelectTrigger className="w-full sm:w-44" aria-label={t("da.filterRisk")}>
            <SelectValue placeholder={t("da.allRisks")} />
          </SelectTrigger>
          <SelectContent>
            {risks.map((r) => (
              <SelectItem key={r} value={r}>
                {r === "all" ? t("da.allRisks") : t(riskKey[r])}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {approvalsResult.isPending && <RowSkeleton />}

      <div className={`mt-6 space-y-4 ${approvalsResult.isPending ? "hidden" : ""}`}>
        {visible.map((item) => {
          const agent = agents.find((a) => a.id === item.agentId);
          return (
            <Card key={item.id}>
              <CardHeader className="flex flex-row items-start gap-3 space-y-0">
                {agent && <AgentAvatar name={agent.name} accent={agent.accent} />}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-base font-semibold tracking-tight">{item.action}</h2>
                    <RiskBadge risk={item.risk} />
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {agent?.name} · {item.requestedAt}
                  </p>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">{item.context}</p>
                <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-border bg-muted/60 p-3 font-mono text-xs text-foreground">
                  {item.preview}
                </pre>
              </CardContent>
              <CardFooter className="grid grid-cols-2 gap-2 border-t bg-card pt-4 sm:flex sm:flex-wrap sm:border-t-0 sm:bg-transparent sm:pt-0">
                <Button size="sm" onClick={() => act(item.id, t("da.approved"))}>
                  <Check className="size-4" /> {t("da.approve")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => act(item.id, t("da.rejected"))}>
                  <X className="size-4" /> {t("da.reject")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => toast.info(t("da.openingEditor"))}
                >
                  <Pencil className="size-4" /> {t("da.edit")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    toast.info(t("da.why", { name: agent?.name ?? "" }))
                  }
                >
                  <HelpCircle className="size-4" /> {t("da.askWhy")}
                </Button>
              </CardFooter>
            </Card>
          );
        })}

        {visible.length === 0 && (
          <div className="rounded-lg border border-dashed border-border py-16 text-center">
            <p className="text-sm font-medium">{t("da.caughtUp")}</p>
            <p className="mt-1 text-sm text-muted-foreground">{t("da.noPending")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
