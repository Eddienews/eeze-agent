import { useEffect } from "react";
import { toast } from "sonner";
import { OctagonX } from "lucide-react";
import { AgentAvatar } from "@/components/agent-avatar";
import { useStore } from "@/components/app-store";
import { TypedConfirmDialog } from "@/components/typed-confirm-dialog";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

export function useKillSwitch() {
  const { agents, killSwitchOpen, setKillSwitchOpen, stopAllAgents } = useStore();
  const activeAgents = agents.filter((agent) => agent.status !== "idle");
  return { agents, activeAgents, killSwitchOpen, setKillSwitchOpen, stopAllAgents };
}

export function KillSwitchTrigger() {
  const t = useT();
  const { setKillSwitchOpen } = useStore();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={t("kill.aria")}
      title={t("kill.title", { keys: "Ctrl+Shift+Alt+K" })}
      onClick={() => setKillSwitchOpen(true)}
      className="text-destructive hover:bg-destructive/10 hover:text-destructive"
    >
      <OctagonX className="size-4" />
    </Button>
  );
}

export function KillSwitchDialog() {
  const { activeAgents, killSwitchOpen, setKillSwitchOpen, stopAllAgents } = useKillSwitch();
  const t = useT();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.shiftKey && event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setKillSwitchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setKillSwitchOpen]);

  const confirm = () => {
    const timestamp = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    stopAllAgents(timestamp);
    setKillSwitchOpen(false);
    toast.error(t("kill.toast", { time: timestamp }), {
      description: t("kill.toastDetail"),
    });
  };

  return (
    <TypedConfirmDialog
      open={killSwitchOpen}
      onOpenChange={setKillSwitchOpen}
      title={t("kill.dialogTitle")}
      description={t("kill.dialogBody")}
      keyword="STOP"
      action={t("kill.action")}
      onConfirm={confirm}
    >
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {t("kill.list")}
        </p>
        {activeAgents.length ? (
          <ul className="mt-3 space-y-2">
            {activeAgents.map((agent) => (
              <li key={agent.id} className="flex items-center gap-3">
                <AgentAvatar name={agent.name} accent={agent.accent} size="sm" />
                <span className="min-w-0 flex-1 truncate text-sm">
                  <span className="font-medium">{agent.name}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    · {agent.currentTask ?? agent.role}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">{t("kill.none")}</p>
        )}
      </div>
    </TypedConfirmDialog>
  );
}
