import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function TypedConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  keyword,
  action,
  onConfirm,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  keyword: string;
  action: string;
  onConfirm: () => void;
  children?: ReactNode;
}) {
  const [value, setValue] = useState("");
  useEffect(() => {
    if (!open) setValue("");
  }, [open]);
  const ready = value.trim().toUpperCase() === keyword;
  const inputId = `confirm-${keyword.toLowerCase()}`;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="w-[calc(100%-2rem)] max-w-[calc(100%-2rem)] sm:max-w-lg">
        <AlertDialogHeader>
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-md bg-destructive/12 text-destructive">
              <AlertTriangle className="size-4" />
            </span>
            <div className="min-w-0 text-left">
              <AlertDialogTitle className="text-balance break-words">{title}</AlertDialogTitle>
              <AlertDialogDescription className="mt-1.5">{description}</AlertDialogDescription>
            </div>
          </div>
        </AlertDialogHeader>
        {children}
        <div>
          <Label htmlFor={inputId}>
            Type <span className="font-mono font-semibold text-destructive">{keyword}</span> to
            confirm
          </Label>
          <Input
            id={inputId}
            value={value}
            autoComplete="off"
            onChange={(event) => setValue(event.target.value)}
            placeholder={keyword}
            className="mt-2 font-mono"
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!ready}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:pointer-events-none disabled:opacity-50"
            onClick={onConfirm}
          >
            {action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
