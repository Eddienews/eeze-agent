import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { type AgentStatus, type RiskLevel } from "@/lib/mock-data";
import { useT, type MessageKey } from "@/lib/i18n";

const statusKeys: Record<AgentStatus, MessageKey> = {
  idle: "badge.idle",
  working: "badge.working",
  needs_approval: "badge.needsApproval",
  error: "badge.error",
};

const riskKeys: Record<RiskLevel, MessageKey> = {
  read: "risk.read",
  write: "badge.write",
  send: "risk.external_send",
  pay: "badge.pay",
  exec: "badge.exec",
};

const statusStyles: Record<AgentStatus, string> = {
  idle: "bg-muted text-muted-foreground border-transparent",
  working: "bg-info/12 text-info border-info/25",
  needs_approval: "bg-warning/15 text-warning border-warning/30",
  error: "bg-destructive/12 text-destructive border-destructive/30",
};

export function StatusBadge({ status, className }: { status: AgentStatus; className?: string }) {
  const t = useT();
  return (
    <Badge variant="outline" className={cn("gap-1.5 font-medium", statusStyles[status], className)}>
      <span
        className={cn("size-1.5 rounded-full bg-current", status === "working" && "animate-pulse")}
      />
      {t(statusKeys[status])}
    </Badge>
  );
}

const riskStyles: Record<RiskLevel, string> = {
  read: "bg-success/12 text-success border-success/25",
  write: "bg-warning/15 text-warning border-warning/30",
  send: "bg-orange/15 text-orange border-orange/30",
  pay: "bg-destructive/12 text-destructive border-destructive/30",
  exec: "bg-info/12 text-info border-info/25",
};

export function RiskBadge({ risk, className }: { risk: RiskLevel; className?: string }) {
  const t = useT();
  return (
    <Badge variant="outline" className={cn("font-medium", riskStyles[risk], className)}>
      {t(riskKeys[risk])}
    </Badge>
  );
}
