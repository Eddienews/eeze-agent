import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api, DEMO_MODE } from "@/lib/api";
import { useT } from "@/lib/i18n";

/** "An update is ready" — new code on disk that the service or the screens have not loaded. */
export function UpdateBanner() {
  const t = useT();
  const fresh = useQuery({
    queryKey: ["freshness"],
    queryFn: ({ signal }) => api.freshness(signal),
    enabled: !DEMO_MODE,
    refetchInterval: 60_000,
    retry: 0,
    staleTime: 30_000,
  });
  if (!fresh.data?.update_ready) return null;
  return (
    <div
      role="status"
      className="border-b border-info/30 bg-info/10 px-4 py-2 text-center text-xs text-foreground"
    >
      <Download className="mr-1.5 inline size-3.5 align-[-2px]" />
      {t("update.ready")}
    </div>
  );
}
