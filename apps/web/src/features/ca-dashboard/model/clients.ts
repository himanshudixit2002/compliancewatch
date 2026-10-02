import type { Tone } from "@compliancewatch/ui";

export const ENGAGEMENT_STATUSES = ["active", "pending", "inactive"] as const;

export type EngagementStatus = (typeof ENGAGEMENT_STATUSES)[number];

/** One client business of a CA firm, with its obligation counts. */
export interface CaClient {
  id: string;
  name: string;
  engagementStatus: EngagementStatus;
  /** Completed obligations as a whole percentage; null before any is due. */
  complianceScore: number | null;
  obligationsDue: number;
  obligationsOverdue: number;
  /** The CA staff member looking after the client; null when unassigned. */
  assignedTo: string | null;
  updatedAt: string;
}

/** The client list's search and status filter, as carried in the page's query string. */
export interface ClientFilter {
  query: string;
  status: EngagementStatus | "all";
}

export interface ClientSummary {
  total: number;
  active: number;
  due: number;
  overdue: number;
  /** The mean of the scores clients have; null when none has one. */
  averageScore: number | null;
}

export const NO_FILTER: ClientFilter = { query: "", status: "all" };

function isEngagementStatus(value: string): value is EngagementStatus {
  return (ENGAGEMENT_STATUSES as readonly string[]).includes(value);
}

function first(value: string | readonly string[] | undefined): string {
  return (typeof value === "string" ? value : value?.[0]) ?? "";
}

/** The filter from search params (`q`, `status`); unknown statuses read as all. */
export function parseClientFilter(
  params: Readonly<Record<string, string | readonly string[] | undefined>>,
): ClientFilter {
  const status = first(params.status);
  return {
    query: first(params.q).trim(),
    status: isEngagementStatus(status) ? status : "all",
  };
}

export function isFiltered(filter: ClientFilter): boolean {
  return filter.query !== "" || filter.status !== "all";
}

/** Clients whose name contains the query (any case) and whose status matches. */
export function filterClients(clients: readonly CaClient[], filter: ClientFilter): CaClient[] {
  const query = filter.query.toLowerCase();
  return clients.filter(
    (client) =>
      (query === "" || client.name.toLowerCase().includes(query)) &&
      (filter.status === "all" || client.engagementStatus === filter.status),
  );
}

export function summarizeClients(clients: readonly CaClient[]): ClientSummary {
  const scores = clients
    .map((client) => client.complianceScore)
    .filter((score): score is number => score !== null);
  return {
    total: clients.length,
    active: clients.filter((client) => client.engagementStatus === "active").length,
    due: clients.reduce((sum, client) => sum + client.obligationsDue, 0),
    overdue: clients.reduce((sum, client) => sum + client.obligationsOverdue, 0),
    averageScore:
      scores.length === 0
        ? null
        : Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length),
  };
}

const ENGAGEMENT_TONE: Readonly<Record<EngagementStatus, Tone>> = {
  active: "success",
  pending: "warning",
  inactive: "neutral",
};

export function engagementTone(status: EngagementStatus): Tone {
  return ENGAGEMENT_TONE[status];
}
