import { RefreshCw, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";

export function RefreshButton({
  onRefresh,
  refreshing,
  label: labelProp,
}: {
  onRefresh: () => void;
  refreshing?: boolean;
  label?: string;
}) {
  const t = useT();
  const label = labelProp ?? t("m.refresh");
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onRefresh}
      disabled={refreshing}
      aria-label={label}
    >
      <RefreshCw className={`size-4 ${refreshing ? "animate-spin" : ""}`} />
      {label}
    </Button>
  );
}

export function ErrorState({
  message: messageProp,
  detail,
  onRetry,
}: {
  message?: string;
  detail?: string;
  onRetry: () => void;
}) {
  const t = useT();
  const message = messageProp ?? t("ds.unreachable");
  return (
    <div className="mt-6 flex flex-col items-center gap-3 rounded-lg border border-dashed p-10 text-center">
      <span className="grid size-10 place-items-center rounded-full bg-destructive/12 text-destructive">
        <WifiOff className="size-5" />
      </span>
      <div>
        <p className="text-sm font-medium">{message}</p>
        {detail && <p className="mt-1 text-sm text-muted-foreground">{detail}</p>}
      </div>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw className="size-4" />
        {t("ds.retry")}
      </Button>
    </div>
  );
}

export function CardSkeletonGrid({ count = 3 }: { count?: number }) {
  return (
    <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="rounded-xl border bg-card p-6">
          <div className="flex items-center gap-3">
            <Skeleton className="size-10 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-3 w-32" />
            </div>
          </div>
          <Skeleton className="mt-5 h-10 w-full" />
          <div className="mt-4 grid grid-cols-3 gap-2">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
          <Skeleton className="mt-4 h-9 w-full" />
        </div>
      ))}
    </div>
  );
}

export function RowSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="mt-6 space-y-3">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-24 w-full rounded-xl" />
      ))}
    </div>
  );
}

export function OfflineNotice({ label }: { label?: string }) {
  const t = useT();
  return (
    <p className="mt-4 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
      {label ?? t("ds.offline")}
    </p>
  );
}
