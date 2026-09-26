import { useEffect } from "react";
import { toast } from "sonner";
import { OctagonX } from "lucide-react";
import { AgentAvatar } from "@/components/agent-avatar";
import { useStore } from "@/components/app-store";
import { TypedConfirmDialog } from "@/components/typed-confirm-dialog";
import { Button } from "@/components/ui/button";

export function useKillSwitch() {
  const { agents, killSwitchOpen, setKillSwitchOpen, stopAllAgents } = useStore();
  const activeAgents = agents.filter((agent) => agent.status !== "idle");
  return { agents, activeAgents, killSwitchOpen, setKillSwitchOpen, stopAllAgents };
}

export function KillSwitchTrigger() {
  const { setKillSwitchOpen } = useStore();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Emergency stop — kill all agents"
      title="Emergency stop (Ctrl+Shift+Alt+K)"
      onClick={() => setKillSwitchOpen(true)}
      className="text-destructive hover:bg-destructive/10 hover:text-destructive"
    >
      <OctagonX className="size-4" />
    </Button>
  );
}

export function KillSwitchDialog() {
  const { activeAgents, killSwitchOpen, setKillSwitchOpen, stopAllAgents } = useKillSwitch();

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
    toast.error(`All agents stopped at ${timestamp}`, {
      description: "cua-driver daemon terminated. Restart it from Settings › System.",
    });
  };

  return (
    <TypedConfirmDialog
      open={killSwitchOpen}
      onOpenChange={setKillSwitchOpen}
      title="Emergency Stop — Kill all agents?"
      description="This will immediately terminate all running agents and stop the cua-driver daemon. No further actions will execute until you manually restart them."
      keyword="STOP"
      action="Kill All"
      onConfirm={confirm}
    >
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Agents that will be killed
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
          <p className="mt-2 text-sm text-muted-foreground">No agents are currently active.</p>
        )}
      </div>
    </TypedConfirmDialog>
  );
}
