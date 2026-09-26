import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import {
  agents as seedAgents,
  approvals as seedApprovals,
  type Agent,
  type Approval,
} from "@/lib/mock-data";

export interface SystemEvent {
  id: string;
  timestamp: string;
  label: string;
  detail: string;
  severity: "critical" | "info";
}

interface Store {
  agents: Agent[];
  approvals: Approval[];
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  killSwitchOpen: boolean;
  setKillSwitchOpen: (open: boolean) => void;
  daemonRunning: boolean;
  setDaemonRunning: (running: boolean) => void;
  systemEvents: SystemEvent[];
  logSystemEvent: (event: Omit<SystemEvent, "id" | "timestamp"> & { timestamp?: string }) => void;
  stopAllAgents: (timestamp: string) => void;
  resolveApproval: (id: string) => void;
  updateAgent: (id: string, patch: Partial<Agent>) => void;
  toggleRoutine: (agentId: string, routineId: string) => void;
  addAgent: (agent: Agent) => void;
  removeAgent: (id: string) => void;
}

const StoreContext = createContext<Store | null>(null);

const now = () =>
  new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<Agent[]>(seedAgents);
  const [approvals, setApprovals] = useState<Approval[]>(seedApprovals);
  const [commandOpen, setCommandOpen] = useState(false);
  const [killSwitchOpen, setKillSwitchOpen] = useState(false);
  const [daemonRunning, setDaemonRunning] = useState(true);
  const [systemEvents, setSystemEvents] = useState<SystemEvent[]>([]);

  const addAgent = useCallback((agent: Agent) => setAgents((list) => [...list, agent]), []);
  const removeAgent = useCallback(
    (id: string) => setAgents((list) => list.filter((agent) => agent.id !== id)),
    [],
  );

  const logSystemEvent = useCallback<Store["logSystemEvent"]>((event) => {
    setSystemEvents((list) => [
      {
        id: `evt-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`,
        timestamp: event.timestamp ?? now(),
        label: event.label,
        detail: event.detail,
        severity: event.severity,
      },
      ...list,
    ]);
  }, []);

  const stopAllAgents = useCallback(
    (timestamp: string) => {
      setAgents((list) =>
        list.map(({ currentTask: _currentTask, ...agent }) => ({
          ...agent,
          status: "idle" as const,
        })),
      );
      setDaemonRunning(false);
      logSystemEvent({
        timestamp,
        label: "Emergency stop executed",
        detail: "All agents terminated and cua-driver daemon stopped.",
        severity: "critical",
      });
    },
    [logSystemEvent],
  );

  const resolveApproval = useCallback(
    (id: string) => setApprovals((list) => list.filter((a) => a.id !== id)),
    [],
  );

  const updateAgent = useCallback(
    (id: string, patch: Partial<Agent>) =>
      setAgents((list) => list.map((a) => (a.id === id ? { ...a, ...patch } : a))),
    [],
  );

  const toggleRoutine = useCallback(
    (agentId: string, routineId: string) =>
      setAgents((list) =>
        list.map((a) =>
          a.id === agentId
            ? {
                ...a,
                routines: a.routines.map((r) =>
                  r.id === routineId ? { ...r, enabled: !r.enabled } : r,
                ),
              }
            : a,
        ),
      ),
    [],
  );

  const value = useMemo(
    () => ({
      agents,
      approvals,
      commandOpen,
      setCommandOpen,
      killSwitchOpen,
      setKillSwitchOpen,
      daemonRunning,
      setDaemonRunning,
      systemEvents,
      logSystemEvent,
      stopAllAgents,
      resolveApproval,
      updateAgent,
      toggleRoutine,
      addAgent,
      removeAgent,
    }),
    [
      agents,
      approvals,
      commandOpen,
      killSwitchOpen,
      daemonRunning,
      systemEvents,
      logSystemEvent,
      stopAllAgents,
      resolveApproval,
      updateAgent,
      toggleRoutine,
      addAgent,
      removeAgent,
    ],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore() {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used inside AppStoreProvider");
  return ctx;
}
