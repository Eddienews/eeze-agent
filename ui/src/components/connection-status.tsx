import { useQuery } from "@tanstack/react-query";
import { API_URL } from "@/lib/api";
import { healthQuery } from "@/lib/queries";
import { useT } from "@/lib/i18n";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export function ConnectionStatus() {
  const t = useT();
  const { data, isPending, isError } = useQuery(healthQuery());
  const online = Boolean(data) && !isError;
  const label = isPending
    ? t("conn.checkingApi")
    : online
      ? t("conn.connected")
      : t("conn.unreachable");

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
              {isPending ? t("conn.checking") : online ? t("conn.live") : t("conn.offline")}
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
