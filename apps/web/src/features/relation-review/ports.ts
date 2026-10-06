import type { CandidateStatus, ClauseDetail, RelationCandidate } from "@/entities/rulebook/types";
import type { RuleSummary, RuleVersion } from "@/entities/rule-version/types";
import type { Result } from "@/server/result";

/** The relation candidate pages' reads; the decisions go through server/api/rulebook-write.ts. */
export interface RelationReviewPort {
  /** Candidates of one status in id order, of one document or every document, after an id. */
  candidates(query: {
    status: CandidateStatus;
    documentId: string | null;
    after: string | null;
    limit: number;
  }): Promise<Result<RelationCandidate[]>>;
  /** The evidence clause with its document's facts. */
  clause(clauseId: string): Promise<Result<ClauseDetail>>;
  /** The rules, for the versions an approval may start from or point at. */
  rules(): Promise<Result<RuleSummary[]>>;
  /** One rule's versions in any status, drafts and closed ones included. */
  versionsOf(ruleKey: string): Promise<Result<RuleVersion[]>>;
}
