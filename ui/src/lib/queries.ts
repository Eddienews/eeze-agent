import { queryOptions } from "@tanstack/react-query";
import { api, DEMO_MODE, fallbacks, type RunFilters } from "@/lib/api";
import { getAgent } from "@/lib/mock-data";

const shared = { retry: DEMO_MODE ? 0 : 1, staleTime: 15_000 } as const;

export const agentsQuery = () =>
  queryOptions({
    queryKey: ["agents"],
    queryFn: ({ signal }) => api.agents(signal),
    ...shared,
  });

export const agentQuery = (id: string) =>
  queryOptions({
    queryKey: ["agents", id],
    queryFn: ({ signal }) => api.agent(id, signal),
    ...shared,
  });

export const runsQuery = (filters: RunFilters = {}) =>
  queryOptions({
    queryKey: ["runs", filters],
    queryFn: ({ signal }) => api.runs(filters, signal),
    ...shared,
  });

export const runQuery = (id: string) =>
  queryOptions({
    queryKey: ["runs", "detail", id],
    queryFn: ({ signal }) => api.run(id, signal),
    ...shared,
  });

export const approvalsQuery = () =>
  queryOptions({
    queryKey: ["approvals"],
    queryFn: ({ signal }) => api.approvals(signal),
    ...shared,
  });

export const approvalQueueQuery = (status?: string) =>
  queryOptions({
    queryKey: ["approval-queue", status ?? "all"],
    queryFn: ({ signal }) => api.approvalQueue(status, signal),
    ...shared,
  });

export const grantsQuery = () =>
  queryOptions({
    queryKey: ["grants"],
    queryFn: ({ signal }) => api.grants(signal),
    ...shared,
  });

export const systemStatusQuery = () =>
  queryOptions({
    queryKey: ["system-status"],
    queryFn: ({ signal }) => api.systemStatus(signal),
    refetchInterval: DEMO_MODE ? false : 10_000,
    retry: 0,
  });

export const systemInfoQuery = () =>
  queryOptions({
    queryKey: ["system-info"],
    queryFn: ({ signal }) => api.systemInfo(signal),
    ...shared,
  });

export const routinesQuery = () =>
  queryOptions({
    queryKey: ["routines"],
    queryFn: ({ signal }) => api.routines(signal),
    ...shared,
  });

export const routineRunsQuery = (id: string, enabled = true) =>
  queryOptions({
    queryKey: ["routines", id, "runs"],
    queryFn: ({ signal }) => api.routineRuns(id, signal),
    enabled,
    ...shared,
  });

export const missionsQuery = () =>
  queryOptions({
    queryKey: ["missions"],
    queryFn: ({ signal }) => api.missions(signal),
    ...shared,
  });

/** Today's estimated model spend per agent vs its daily cap (header chip). */
export const spendTodayQuery = () =>
  queryOptions({
    queryKey: ["spend-today"],
    queryFn: ({ signal }) => api.spendToday(signal),
    refetchInterval: DEMO_MODE ? false : 30_000,
    retry: 0,
    staleTime: 10_000,
  });

export const setupStateQuery = () =>
  queryOptions({
    queryKey: ["setup-state"],
    queryFn: ({ signal }) => api.setupState(signal),
    retry: 0,
    staleTime: 5_000,
  });

/** Providers + their live status (Settings, P3). Presence and last4 only — never a key. */
export const providersQuery = () =>
  queryOptions({
    queryKey: ["providers"],
    queryFn: ({ signal }) => api.providers(signal),
    ...shared,
  });

/** Health probe used by the header connection indicator. */
export const healthQuery = () =>
  queryOptions({
    queryKey: ["api-health"],
    queryFn: async ({ signal }) => {
      await api.health(signal);
      return true;
    },
    refetchInterval: DEMO_MODE ? false : 10_000,
    retry: 0,
    staleTime: 0,
  });

export const fallbackAgents = fallbacks.agents;
export const fallbackApprovals = fallbacks.approvals;
export const fallbackAgent = getAgent;
