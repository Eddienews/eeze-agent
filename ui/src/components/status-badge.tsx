import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { statusLabel, riskLabel, type AgentStatus, type RiskLevel } from "@/lib/mock-data";

const statusStyles: Record<AgentStatus, string> = {
  idle: "bg-muted text-muted-foreground border-transparent",
  working: "bg-info/12 text-info border-info/25",
  needs_approval: "bg-warning/15 text-warning border-warning/30",
  error: "bg-destructive/12 text-destructive border-destructive/30",
};

export function StatusBadge({ status, className }: { status: AgentStatus; className?: string }) {
  return (
    <Badge variant="outline" className={cn("gap-1.5 font-medium", statusStyles[status], className)}>
      <span
        className={cn("size-1.5 rounded-full bg-current", status === "working" && "animate-pulse")}
      />
      {statusLabel[status]}
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
  return (
    <Badge variant="outline" className={cn("font-medium", riskStyles[risk], className)}>
      {riskLabel[risk]}
    </Badge>
  );
}
