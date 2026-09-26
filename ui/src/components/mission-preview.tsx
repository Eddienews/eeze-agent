import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Box, Download, FileVideo, ImageIcon, ListChecks } from "lucide-react";
import { api, DEMO_MODE, type ApiMediaFile, type MissionKind } from "@/lib/api";
import { FilesPlanPreview, FilesRunReport } from "@/components/files-preview";
import { useI18n, useT } from "@/lib/i18n";

/** Statuses during which a mission's files may still change. */
export const LIVE_STATUSES = new Set(["running", "needs_approval"]);

function prettySize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Thumbnails for images, inline players for videos, download links for 3D files. */
export function MediaGrid({
  files,
  emptyText,
  compact = false,
}: {
  files: ApiMediaFile[];
  emptyText: string;
  compact?: boolean;
}) {
  const t = useT();
  if (files.length === 0) {
    return <p className="text-xs text-muted-foreground">{emptyText}</p>;
  }
  return (
    <div className={`grid gap-2 ${compact ? "grid-cols-3 sm:grid-cols-4" : "grid-cols-2 sm:grid-cols-3"}`}>
      {files.map((file) => (
        <figure
          key={file.url}
          className="overflow-hidden rounded-md border border-border bg-muted/40"
        >
          {file.kind === "image" ? (
            <a href={file.url} target="_blank" rel="noreferrer" title={t("r.openFull")}>
              <img
                src={file.url}
                alt={file.name}
                loading="lazy"
                className={`w-full object-contain ${compact ? "h-20" : "h-40"} bg-[repeating-conic-gradient(#8881_0_25%,transparent_0_50%)] bg-[length:16px_16px]`}
              />
            </a>
          ) : file.kind === "video" ? (
            <video
              src={file.url}
              controls
              preload="metadata"
              className={`w-full bg-black ${compact ? "h-20" : "h-40"}`}
            />
          ) : (
            <a
              href={file.url}
              download
              className={`flex w-full flex-col items-center justify-center gap-1 text-xs text-muted-foreground hover:text-foreground ${compact ? "h-20" : "h-40"}`}
            >
              <Box className="size-6" />
              {t("r.download")}
            </a>
          )}
          <figcaption className="flex items-center gap-1 truncate px-2 py-1 text-[11px] text-muted-foreground">
            {file.kind === "image" ? (
              <ImageIcon className="size-3 shrink-0" />
            ) : file.kind === "video" ? (
              <FileVideo className="size-3 shrink-0" />
            ) : (
              <Download className="size-3 shrink-0" />
            )}
            <span className="truncate">{file.name}</span>
            <span className="ml-auto shrink-0">{prettySize(file.size)}</span>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

/** "Before" (the source media) next to "Result" (what the last run produced). */
export function MissionResults({ missionId, status }: { missionId: string; status?: string | null }) {
  const t = useT();
  const outputs = useQuery({
    queryKey: ["missions", missionId, "outputs", status ?? ""],
    queryFn: ({ signal }) => api.missionOutputs(missionId, signal),
    enabled: !DEMO_MODE && Boolean(missionId),
    refetchInterval: status === "running" ? 4_000 : LIVE_STATUSES.has(status ?? "") ? 15_000 : false,
    staleTime: 2_000,
  });
  if (!outputs.data) return null;
  const { sources } = outputs.data;
  const files = outputs.data.files.filter((file) => !file.step);
  const steps = outputs.data.files.filter((file) => file.step);
  if (outputs.data.report) {
    return <FilesRunReport missionId={missionId} report={outputs.data.report} />;
  }
  if (files.length === 0 && sources.length === 0) return null;
  return (
    <div className="mt-4 grid gap-4 md:grid-cols-2">
      {sources.length > 0 && (
        <section>
          <p className="mb-2 text-xs font-medium">{t("r.before")}</p>
          <MediaGrid files={sources} emptyText="" compact={files.length > 0} />
        </section>
      )}
      <section className={sources.length === 0 ? "md:col-span-2" : ""}>
        <p className="mb-2 text-xs font-medium">
          {t("r.result")} {status === "running" ? t("r.working") : ""}
        </p>
        <MediaGrid
          files={files}
          emptyText={
            status === "running"
              ? t("r.runningEmpty")
              : status === "needs_approval"
                ? t("r.waitingEmpty")
                : t("r.none")
          }
        />
        {steps.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-[11px] text-muted-foreground">
              {t("r.steps", { n: steps.length })}
            </summary>
            <div className="mt-2">
              <MediaGrid files={steps} emptyText="" compact />
            </div>
          </details>
        )}
      </section>
    </div>
  );
}

/** Plain-language summary of a plan (server-side, best effort). */
export function PlanSummary({ kind, plan }: { kind: MissionKind; plan: string }) {
  const { lang } = useI18n();
  // Debounced: typing in the plan editor must not post a request per keystroke.
  const [settled, setSettled] = useState(plan);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(plan), 600);
    return () => clearTimeout(timer);
  }, [plan]);
  const summary = useQuery({
    queryKey: ["plan-summary", kind, settled, lang],
    queryFn: () => api.describePlan(kind, settled, lang),
    enabled: !DEMO_MODE && settled.trim().length > 0,
    staleTime: 60_000,
    gcTime: 60_000,
    placeholderData: (previous) => previous,
  });
  const lines = summary.data?.lines ?? [];
  if (lines.length === 0) return null;
  return (
    <ol className="space-y-1 text-sm">
      {lines.map((line, index) => (
        <li key={index} className="flex gap-2">
          <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-muted text-[10px] font-medium text-muted-foreground">
            {index + 1}
          </span>
          <span>{line}</span>
        </li>
      ))}
    </ol>
  );
}

/** Shown on an approval card when the paused run is a mission: what it will do, on which files. */
export function MissionApprovalPreview({ missionId }: { missionId: string }) {
  const t = useT();
  const mission = useQuery({
    queryKey: ["missions", "detail", missionId],
    queryFn: ({ signal }) => api.mission(missionId, signal),
    enabled: !DEMO_MODE && Boolean(missionId),
    retry: 0,
  });
  const outputs = useQuery({
    queryKey: ["missions", missionId, "outputs"],
    queryFn: ({ signal }) => api.missionOutputs(missionId, signal),
    enabled: !DEMO_MODE && Boolean(missionId),
    retry: 0,
  });
  const row = mission.data;
  if (!row) return null;
  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <p className="flex items-center gap-1.5 text-sm font-medium">
        <ListChecks className="size-4" /> {t("r.willDo", { name: row.name })}
      </p>
      <PlanSummary kind={row.kind} plan={row.plan ?? ""} />
      {row.kind === "files" && <FilesPlanPreview plan={row.plan ?? ""} />}
      {(outputs.data?.sources.length ?? 0) > 0 && (
        <div>
          <p className="mb-1.5 text-xs text-muted-foreground">
            {t("r.onFiles")}
          </p>
          <MediaGrid files={outputs.data?.sources ?? []} emptyText="" compact />
        </div>
      )}
    </div>
  );
}

/** Mission id from an approval title like "mission-<id> · run". */
export function missionIdFromApprovalTitle(title: string): string | null {
  const task = title.split(" · ")[0] ?? "";
  return task.startsWith("mission-") ? task.slice("mission-".length) : null;
}
