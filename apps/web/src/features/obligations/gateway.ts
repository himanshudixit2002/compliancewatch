import "server-only";

import { decisionFromDto } from "@/entities/applicability/mappers";
import type { Decision } from "@/entities/applicability/types";
import { businessFromDto } from "@/entities/business/mappers";
import type { Business } from "@/entities/business/types";
import {
  obligationCommentFromDto,
  obligationDetailFromDto,
  obligationFromDto,
  obligationPageFromDto,
  statusChangeToDto,
} from "@/entities/obligation/mappers";
import type {
  Obligation,
  ObligationComment,
  ObligationDetail,
  ObligationPage,
  StatusChange,
} from "@/entities/obligation/types";
import { clauseDetailFromDto } from "@/entities/rulebook/mappers";
import type { ClauseDetail } from "@/entities/rulebook/types";
import { call } from "@/server/api/client";
import { callIdempotent, type Replayable } from "@/server/api/idempotency";
import {
  applicabilityEngineClient,
  identityClient,
  obligationClient,
  profileClient,
  rulebookClient,
  type ApplicabilityEngineClient,
  type ClientContext,
  type IdentityClient,
  type ObligationClient,
  type ProfileClient,
  type RulebookClient,
} from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, mapResult, type Result } from "@/server/result";
import type {
  BusinessPort,
  ClausesPort,
  DecisionsPort,
  NodeListQuery,
  ObligationsPort,
  TeamMember,
  TeamPort,
  WriteHeaders,
} from "./ports";

type KeyHeader = { "Idempotency-Key": string };

/** A replayed write's answer mapped like a fresh one; a success without a body is an error. */
function mapReplayable<T, U>(
  result: Result<Replayable<T | undefined>>,
  fn: (value: T) => U,
): Result<Replayable<U>> {
  if (!result.ok) return result;
  const { replayed } = result.value;
  return mapBody(
    mapResult(result, (answer) => answer.value),
    (value: T) => ({
      value: fn(value),
      replayed,
    }),
  );
}

/**
 * The obligation screens' reads and writes over the typed clients: the obligation service (a
 * node's list on the public API, one obligation and its tracking writes under the service's own
 * prefix), the profile service (the business and its nodes), the applicability engine (the
 * decisions of a node) and identity (the tenant's users), all tenant data, never cached; and the
 * rulebook's clauses, the same for every tenant and kept five minutes under their tag. The
 * Idempotency-Key of a write comes from the form; the spec marks it required.
 */
export class ObligationsGateway
  implements ObligationsPort, BusinessPort, DecisionsPort, ClausesPort, TeamPort
{
  private readonly obligation: ObligationClient;
  private readonly profile: ProfileClient;
  private readonly engine: ApplicabilityEngineClient;
  private readonly identity: IdentityClient;
  private readonly rulebook: RulebookClient;

  constructor(ctx: ClientContext) {
    this.obligation = obligationClient(ctx);
    this.profile = profileClient(ctx);
    this.engine = applicabilityEngineClient(ctx);
    this.identity = identityClient(ctx);
    this.rulebook = rulebookClient({ fetchImpl: ctx.fetchImpl });
  }

  async business(businessId: string): Promise<Result<Business>> {
    const result = await call(
      this.profile.GET("/v1/businesses/{business_id}", {
        params: { path: { business_id: businessId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, businessFromDto);
  }

  async list(nodeId: string, query: NodeListQuery): Promise<Result<ObligationPage>> {
    const result = await call(
      this.obligation.GET("/v1/businesses/{business_id}/obligations", {
        params: {
          path: { business_id: nodeId },
          query: {
            limit: query.limit,
            ...(query.statuses.length === 0 ? {} : { status: [...query.statuses] }),
            ...(query.dueFrom === null ? {} : { due_from: query.dueFrom }),
            ...(query.dueTo === null ? {} : { due_to: query.dueTo }),
            ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, obligationPageFromDto);
  }

  async detail(obligationId: string): Promise<Result<ObligationDetail>> {
    const result = await call(
      this.obligation.GET("/v1/obligation/obligations/{obligation_id}", {
        params: { path: { obligation_id: obligationId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, obligationDetailFromDto);
  }

  async changeStatus(
    obligationId: string,
    change: StatusChange,
    headers: WriteHeaders,
  ): Promise<Result<Replayable<Obligation>>> {
    const result = await callIdempotent(
      this.obligation.POST("/v1/obligation/obligations/{obligation_id}/status", {
        params: { path: { obligation_id: obligationId }, header: headers as KeyHeader },
        body: statusChangeToDto(change),
      }),
    );
    return mapReplayable(result, obligationFromDto);
  }

  async assign(
    obligationId: string,
    assigneeId: string | null,
    headers: WriteHeaders,
  ): Promise<Result<Replayable<Obligation>>> {
    const result = await callIdempotent(
      this.obligation.PUT("/v1/obligation/obligations/{obligation_id}/assignee", {
        params: { path: { obligation_id: obligationId }, header: headers as KeyHeader },
        body: { assignee_id: assigneeId },
      }),
    );
    return mapReplayable(result, obligationFromDto);
  }

  async comment(
    obligationId: string,
    body: string,
    headers: WriteHeaders,
  ): Promise<Result<Replayable<ObligationComment>>> {
    const result = await callIdempotent(
      this.obligation.POST("/v1/obligation/obligations/{obligation_id}/comments", {
        params: { path: { obligation_id: obligationId }, header: headers as KeyHeader },
        body: { body },
      }),
    );
    return mapReplayable(result, obligationCommentFromDto);
  }

  /** The newest decision of the version for the node (the route lists newest first). */
  async latestDecision(nodeId: string, ruleVersionId: string): Promise<Result<Decision | null>> {
    const result = await call(
      this.engine.GET("/v1/applicability-engine/businesses/{business_id}/decisions", {
        params: {
          path: { business_id: nodeId },
          query: { rule_version_id: ruleVersionId, limit: 1 },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (page) => {
      const first = page.items[0];
      return first === undefined ? null : decisionFromDto(first);
    });
  }

  /** A clause never changes under its id: kept five minutes under its tag. */
  async clause(clauseId: string): Promise<Result<ClauseDetail>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/clauses/{clause_id}", {
        params: { path: { clause_id: clauseId } },
        ...cachedRead([tags.rulebook.clause(clauseId)]),
      }),
    );
    return mapBody(result, clauseDetailFromDto);
  }

  /** The tenant's active users, by display name; never their contact details. */
  async members(): Promise<Result<readonly TeamMember[]>> {
    const result = await call(this.identity.GET("/v1/identity/users", { ...uncachedRead() }));
    return mapBody(result, (users) =>
      users.items
        .filter((user) => user.status === "active")
        .map((user) => ({ id: user.id, name: user.display_name, roles: [...user.roles] })),
    );
  }
}

/** The gateway for a page or an action; tests add fetchImpl. */
export function obligationsGateway(ctx: ClientContext): ObligationsGateway {
  return new ObligationsGateway(ctx);
}
