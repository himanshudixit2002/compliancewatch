import type { Decision } from "@/entities/applicability/types";
import type { Business } from "@/entities/business/types";
import type {
  Obligation,
  ObligationComment,
  ObligationDetail,
  ObligationPage,
  ObligationStatus,
  StatusChange,
} from "@/entities/obligation/types";
import type { ClauseDetail } from "@/entities/rulebook/types";
import type { Replayable } from "@/server/api/idempotency";
import type { Result } from "@/server/result";

/** The headers a write carries: the form's Idempotency-Key, or nothing. */
export type WriteHeaders = Readonly<Record<string, string>>;

export interface NodeListQuery {
  statuses: readonly ObligationStatus[];
  /** Date keys in India, both ends included. */
  dueFrom: string | null;
  dueTo: string | null;
  limit: number;
  /** The service's cursor of the node's next page. */
  cursor?: string;
}

/**
 * What the obligation screens need from the obligation service: one node's obligations a page at
 * a time, one obligation with its history and comments, and the three tracking writes, each with
 * the form's Idempotency-Key and the answer saying whether it was a replay.
 */
export interface ObligationsPort {
  list(nodeId: string, query: NodeListQuery): Promise<Result<ObligationPage>>;
  detail(obligationId: string): Promise<Result<ObligationDetail>>;
  changeStatus(
    obligationId: string,
    change: StatusChange,
    headers: WriteHeaders,
  ): Promise<Result<Replayable<Obligation>>>;
  assign(
    obligationId: string,
    assigneeId: string | null,
    headers: WriteHeaders,
  ): Promise<Result<Replayable<Obligation>>>;
  comment(
    obligationId: string,
    body: string,
    headers: WriteHeaders,
  ): Promise<Result<Replayable<ObligationComment>>>;
}

/** And the business the obligations are of, with its nodes, from the profile service. */
export interface BusinessPort {
  business(businessId: string): Promise<Result<Business>>;
}

/** And the engine's latest decision of a rule version for a node: why the obligation applies. */
export interface DecisionsPort {
  latestDecision(nodeId: string, ruleVersionId: string): Promise<Result<Decision | null>>;
}

/** And a cited clause with its document's facts, the same for every tenant. */
export interface ClausesPort {
  clause(clauseId: string): Promise<Result<ClauseDetail>>;
}

/** A user of the tenant an obligation can be given to. */
export interface TeamMember {
  id: string;
  name: string;
  roles: readonly string[];
}

/** And the tenant's active users, which only a tenant admin may read. */
export interface TeamPort {
  members(): Promise<Result<readonly TeamMember[]>>;
}
