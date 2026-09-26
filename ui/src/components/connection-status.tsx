import { useQuery } from "@tanstack/react-query";
import { API_URL } from "@/lib/api";
import { healthQuery } from "@/lib/queries";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export function ConnectionStatus() {
  const { data, isPending, isError } = useQuery(healthQuery());
  const online = Boolean(data) && !isError;
  const label = isPending
    ? "Checking API…"
    : online
      ? "API connected"
      : "API unreachable — showing sample data";

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            role="status"
            aria-label={`${label} (${API_URL})`}
            className="flex items-center gap-1.5 rounded-full border border-border px-2 py-1"
          >
            <span
              className={`size-2 rounded-full ${isPending ? "bg-muted-foreground" : online ? "bg-success" : "bg-destructive"}`}
            />
            <span className="hidden text-[11px] font-medium text-muted-foreground sm:inline">
              {isPending ? "Checking" : online ? "Live" : "Offline"}
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          <p>{label}</p>
          <p className="mt-1 font-mono text-[11px] opacity-80">{API_URL}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
