import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, Copy, TriangleAlert, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, DEMO_MODE, type ApiFileChange, type ApiFilesReport } from "@/lib/api";
import { useT } from "@/lib/i18n";

function ChangeTable({ changes, limit = 12 }: { changes: ApiFileChange[]; limit?: number }) {
  const t = useT();
  const [all, setAll] = useState(false);
  const shown = all ? changes : changes.slice(0, limit);
  return (
    <div className="overflow-hidden rounded-md border border-border">
      <table className="w-full text-xs">
        <thead className="bg-muted/60 text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">{t("files.before")}</th>
            <th className="w-6" />
            <th className="px-2 py-1.5 text-left font-medium">{t("files.after")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {shown.map((change) => (
            <tr key={change.from}>
              <td className="truncate px-2 py-1 font-mono">{change.from}</td>
              <td className="text-muted-foreground">
                <ArrowRight className="size-3" />
              </td>
              <td className="truncate px-2 py-1 font-mono">{change.to}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {changes.length > limit && (
        <button
          type="button"
          onClick={() => setAll((value) => !value)}
          className="w-full border-t border-border py-1 text-[11px] text-muted-foreground hover:text-foreground"
        >
          {all ? t("files.showLess") : t("files.showAll", { n: changes.length })}
        </button>
      )}
    </div>
  );
}

function Duplicates({ groups }: { groups: string[][] }) {
  const t = useT();
  if (groups.length === 0) return <p className="text-xs text-muted-foreground">{t("files.noDuplicates")}</p>;
  return (
    <ul className="space-y-1 text-xs">
      {groups.map((group) => (
        <li key={group.join("|")} className="flex items-start gap-1.5">
          <Copy className="mt-0.5 size-3 shrink-0 text-muted-foreground" />
          <span className="font-mono">{group.join("  =  ")}</span>
        </li>
      ))}
    </ul>
  );
}

/** Live "before → after" preview of a files plan (nothing changes until approved). */
export function FilesPlanPreview({ plan }: { plan: string }) {
  const t = useT();
  const [settled, setSettled] = useState(plan);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(plan), 600);
    return () => clearTimeout(timer);
  }, [plan]);
  const preview = useQuery({
    queryKey: ["files-preview", settled],
    queryFn: () => api.filesPreview(settled),
    enabled: !DEMO_MODE && settled.trim().length > 0,
    staleTime: 10_000,
    placeholderData: (previous) => previous,
  });
  const data = preview.data;
  if (!data) return null;
  if (!data.ok) {
    return <p className="text-xs text-destructive">{data.error}</p>;
  }
  const changes = data.changes ?? [];
  const conflicts = data.conflicts ?? [];
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium">
        {data.op === "duplicates"
          ? t("files.previewDuplicates", { n: data.files ?? 0 })
          : t("files.previewChanges", { n: data.total_changes ?? changes.length, total: data.files ?? 0 })}
      </p>
      {conflicts.length > 0 && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs">
          <p className="flex items-center gap-1.5 font-medium">
            <TriangleAlert className="size-3.5" /> {t("files.conflicts")}
          </p>
          <ul className="mt-1 list-disc pl-4">
            {conflicts.slice(0, 8).map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}
      {data.op === "duplicates" ? (
        <Duplicates groups={data.duplicates ?? []} />
      ) : changes.length > 0 ? (
        <ChangeTable changes={changes} />
      ) : (
        <p className="text-xs text-muted-foreground">{t("files.nothingToChange")}</p>
      )}
    </div>
  );
}

/** What a finished files run did, with the Undo button. */
export function FilesRunReport({ missionId, report }: { missionId: string; report: ApiFilesReport }) {
  const t = useT();
  const queryClient = useQueryClient();
  const undo = useMutation({
    mutationFn: () => api.undoMission(missionId),
    onSuccess: (result) => {
      toast.success(t("files.undone", { n: result.restored }));
      void queryClient.invalidateQueries({ queryKey: ["missions"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const changes = report.changes ?? [];
  return (
    <section className="mt-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-medium">
          {report.error
            ? t("files.failed", { error: report.error })
            : report.op === "duplicates"
              ? t("files.duplicatesFound", { n: (report.duplicates ?? []).length })
              : report.undone
                ? t("files.wasUndone", { n: report.applied ?? 0 })
                : t("files.applied", { n: report.applied ?? 0 })}
        </p>
        {report.op !== "duplicates" && (report.applied ?? 0) > 0 && !report.undone && (
          <Button size="sm" variant="outline" disabled={undo.isPending} onClick={() => undo.mutate()}>
            <Undo2 className="mr-1.5 size-3.5" /> {t("files.undo")}
          </Button>
        )}
      </div>
      {report.op === "duplicates" ? (
        <Duplicates groups={report.duplicates ?? []} />
      ) : (
        changes.length > 0 && <ChangeTable changes={changes} />
      )}
    </section>
  );
}
