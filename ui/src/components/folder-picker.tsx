import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Check, FileImage, Folder, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, DEMO_MODE } from "@/lib/api";
import { useT } from "@/lib/i18n";

/**
 * "Browse…" for a folder (or one media file) on this computer. Browsers cannot hand a
 * page the full path of a picked folder, so the local service lists folder names instead.
 */
export function FolderPicker({
  value,
  onPick,
  allowFiles = false,
}: {
  value: string;
  onPick: (path: string) => void;
  allowFiles?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState<string | null>(null);
  const listing = useQuery({
    queryKey: ["fs", path ?? "", allowFiles],
    queryFn: ({ signal }) => api.fsList(path, allowFiles, signal),
    enabled: open && !DEMO_MODE,
    retry: 0,
    staleTime: 5_000,
  });
  const data = listing.data;
  const join = (base: string, name: string) =>
    base.endsWith("\\") || base.endsWith("/")
      ? `${base}${name}`
      : `${base}${base.includes("\\") ? "\\" : "/"}${name}`;

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          setPath(value.trim().replace(/^"|"$/g, "") || null);
          setOpen(true);
        }}
      >
        <FolderOpen className="mr-1.5 size-4" /> {t("picker.browse")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{allowFiles ? t("picker.titleFile") : t("picker.title")}</DialogTitle>
            <DialogDescription className="break-all font-mono text-xs">
              {data?.path ?? "…"}
            </DialogDescription>
          </DialogHeader>
          {listing.isError && (
            <p className="text-xs text-destructive">
              {(listing.error as Error).message} — {t("picker.goBack")}
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-[170px_1fr]">
            <nav className="flex flex-wrap gap-1 sm:flex-col">
              {(data?.places ?? []).map((place) => (
                <button
                  key={place.path}
                  type="button"
                  onClick={() => setPath(place.path)}
                  className="truncate rounded px-2 py-1 text-left text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  {place.label}
                </button>
              ))}
            </nav>
            <div className="max-h-80 overflow-y-auto rounded-md border border-border">
              {data?.parent && (
                <button
                  type="button"
                  onClick={() => setPath(data.parent)}
                  className="flex w-full items-center gap-2 border-b border-border px-3 py-1.5 text-left text-xs hover:bg-accent"
                >
                  <ArrowUp className="size-3.5" /> ..
                </button>
              )}
              {(data?.dirs ?? []).map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => data && setPath(join(data.path, name))}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent"
                >
                  <Folder className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{name}</span>
                </button>
              ))}
              {allowFiles &&
                (data?.files ?? []).map((file) => (
                  <button
                    key={file.path}
                    type="button"
                    onClick={() => {
                      onPick(file.path);
                      setOpen(false);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent"
                  >
                    <FileImage className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{file.name}</span>
                  </button>
                ))}
              {data && data.dirs.length === 0 && (!allowFiles || data.files.length === 0) && (
                <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                  {t("picker.empty")}
                </p>
              )}
            </div>
          </div>
          <DialogFooter className="items-center gap-2 sm:justify-between">
            <span className="text-xs text-muted-foreground">
              {data ? t("picker.media", { n: data.media_count }) : ""}
            </span>
            <Button
              type="button"
              disabled={!data}
              onClick={() => {
                if (data) onPick(data.path);
                setOpen(false);
              }}
            >
              <Check className="mr-1.5 size-4" /> {t("picker.useFolder")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
