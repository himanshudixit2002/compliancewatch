import "server-only";

import { clauseDetailFromDto, relationCandidateFromDto } from "@/entities/rulebook/mappers";
import type { CandidateStatus, ClauseDetail, RelationCandidate } from "@/entities/rulebook/types";
import { ruleFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { RuleSummary, RuleVersion } from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import { rulebookClient, type ClientContext, type RulebookClient } from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { RelationReviewPort } from "./ports";

/**
 * The relation candidate pages over the typed rulebook client, with no tenant header and no
 * token. The candidates and the versions are read fresh: the pipeline stages candidates and
 * analysts decide them and move versions outside this server. A clause never changes under its
 * id and the rule list is a global registry, so both are cached under their tags (D-018).
 */
export class RelationReviewGateway implements RelationReviewPort {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
  }

  async candidates(query: {
    status: CandidateStatus;
    documentId: string | null;
    after: string | null;
    limit: number;
  }): Promise<Result<RelationCandidate[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/relations", {
        params: {
          query: {
            status: query.status,
            limit: query.limit,
            ...(query.documentId === null ? {} : { document_id: query.documentId }),
            ...(query.after === null ? {} : { after: query.after }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (candidates) => candidates.map(relationCandidateFromDto));
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

  async rules(): Promise<Result<RuleSummary[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rules", { ...cachedRead([tags.rulebook.rules()]) }),
    );
    return mapBody(result, (rules) => rules.map(ruleFromDto));
  }

  async versionsOf(ruleKey: string): Promise<Result<RuleVersion[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rules/{rule_key}/versions", {
        params: { path: { rule_key: ruleKey } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (versions) => versions.map(ruleVersionFromDto));
  }
}

/** The gateway for the relation candidate pages; tests add fetchImpl. */
export function relationReviewGateway(
  ctx: Pick<ClientContext, "fetchImpl"> = {},
): RelationReviewGateway {
  return new RelationReviewGateway(ctx);
}
