import "server-only";

import { clauseDetailFromDto, relationFromDto } from "@/entities/rulebook/mappers";
import type { ClauseDetail, RuleRelation } from "@/entities/rulebook/types";
import { citationFromDto, ruleFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { Citation, RuleSummary, RuleVersion } from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import { rulebookClient, type ClientContext, type RulebookClient } from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { RuleVersionsPort } from "./ports";

/** The most relations one read asks for; the route serves up to 500. */
export const RELATIONS_LIMIT = 200;

/**
 * The rulebook's open reads over rules, rule versions, citations, clauses and relations, with no
 * tenant header and no token (the records belong to no tenant). A version moves through the
 * review flow outside this server too (the seed command, another analyst), so the version, rule
 * and relation reads are never cached; a clause never changes under its id, so its read is kept
 * five minutes under its own tag, as a document is.
 */
export class RuleVersionsGateway implements RuleVersionsPort {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
  }

  async rules(): Promise<Result<readonly RuleSummary[]>> {
    const result = await call(this.rulebook.GET("/v1/rulebook/rules", { ...uncachedRead() }));
    return mapBody(result, (body) => body.map(ruleFromDto));
  }

  async versionsOf(ruleKey: string): Promise<Result<readonly RuleVersion[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rules/{rule_key}/versions", {
        params: { path: { rule_key: ruleKey } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => body.map(ruleVersionFromDto));
  }

  async inForce(query: {
    asOf: string;
    ruleKey?: string;
    limit: number;
    after?: string;
  }): Promise<Result<readonly RuleVersion[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rule-versions", {
        params: {
          query: {
            as_of: query.asOf,
            limit: query.limit,
            ...(query.ruleKey === undefined ? {} : { rule_key: query.ruleKey }),
            ...(query.after === undefined ? {} : { after: query.after }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => body.map(ruleVersionFromDto));
  }

  async version(ruleVersionId: string): Promise<Result<RuleVersion>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rule-versions/{rule_version_id}", {
        params: { path: { rule_version_id: ruleVersionId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, ruleVersionFromDto);
  }

  async citations(ruleVersionId: string): Promise<Result<readonly Citation[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rule-versions/{rule_version_id}/citations", {
        params: { path: { rule_version_id: ruleVersionId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => body.map(citationFromDto));
  }

  async clause(clauseId: string): Promise<Result<ClauseDetail>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/clauses/{clause_id}", {
        params: { path: { clause_id: clauseId } },
        ...cachedRead([tags.rulebook.clause(clauseId)]),
      }),
    );
    return mapBody(result, clauseDetailFromDto);
  }

  async relations(query: { from?: string; to?: string }): Promise<Result<readonly RuleRelation[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/relations", {
        params: {
          query: {
            // Drafts' relations too: an analyst prepares them before the version is published.
            published_only: false,
            limit: RELATIONS_LIMIT,
            ...(query.from === undefined ? {} : { from_rule_version_id: query.from }),
            ...(query.to === undefined ? {} : { to_rule_version_id: query.to }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => body.map(relationFromDto));
  }
}

/** The gateway for a page or an action; tests add fetchImpl. */
export function ruleVersionsGateway(
  ctx: Pick<ClientContext, "fetchImpl"> = {},
): RuleVersionsGateway {
  return new RuleVersionsGateway(ctx);
}
