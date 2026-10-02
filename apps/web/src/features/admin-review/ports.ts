import type { Result } from "@/server/result";

export interface EntityGroupOut {
  entity_type: string;
  proposed_name: string;
  open_count: number;
  examples: {
    review_id: string;
    document_id: string;
    clause_id: string;
    mention_text: string;
    span_start: number;
    span_end: number;
    reason: string;
  }[];
}

export interface RelationCandidateOut {
  candidate_id: string;
  document_id: string;
  relation: string;
  target_type: string;
  target_name: string;
  target_entity_id: string | null;
  target_rule_key: string | null;
  evidence_clause_id: string;
  evidence_quote: string;
  quote_score: number;
  confidence: number;
  needs_review: boolean;
  status: string;
  issues: { code: string; detail?: string }[];
}

export interface ReviewPort {
  entityGroups(): Promise<Result<EntityGroupOut[]>>;
  openCandidates(): Promise<Result<RelationCandidateOut[]>>;
  groupItems(
    entityType: string,
    proposedName: string,
  ): Promise<Result<{ review_id: string; mention_text: string; reason: string }[]>>;
}
