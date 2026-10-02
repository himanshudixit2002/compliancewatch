import "server-only";

import { reviewReadGateway } from "./gateway";
import type { EntityType } from "@/entities/rulebook/types";

export interface ReviewData {
  entityGroups: {
    entityType: string;
    proposedName: string;
    openCount: number;
    examples: {
      reviewId: string;
      documentId: string;
      clauseId: string;
      mentionText: string;
      spanStart: number;
      spanEnd: number;
      reason: string;
    }[];
  }[];
  relations: {
    candidateId: string;
    documentId: string;
    relation: string;
    targetType: string;
    targetName: string;
    evidenceClauseId: string;
    evidenceQuote: string;
    quoteScore: number;
    confidence: number;
    needsReview: boolean;
    issues: { code: string; detail?: string }[];
  }[];
}

export async function getReviewData(
  deps: { fetchImpl?: Parameters<typeof reviewReadGateway>[0] extends { fetchImpl?: infer F } ? F : never } = {},
): Promise<ReviewData> {
  const gateway = reviewReadGateway({ fetchImpl: deps.fetchImpl });
  const [groupsResult, candidatesResult] = await Promise.all([
    gateway.entityGroups(),
    gateway.openCandidates(),
  ]);

  const entityGroups: ReviewData["entityGroups"] = [];
  if (groupsResult.ok) {
    for (const dto of groupsResult.value) {
      let examples: ReviewData["entityGroups"][number]["examples"] = [];
      if (dto.examples.length > 0) {
        const itemsResult = await gateway.groupItems(dto.entity_type as EntityType, dto.proposed_name);
        if (itemsResult.ok) {
          examples = itemsResult.value.map((item: { review_id: string; document_id: string; clause_id: string; mention_text: string; span_start: number; span_end: number; reason: string }) => ({
            reviewId: item.review_id,
            documentId: item.document_id,
            clauseId: item.clause_id,
            mentionText: item.mention_text,
            spanStart: item.span_start,
            spanEnd: item.span_end,
            reason: item.reason,
          }));
        }
      }
      entityGroups.push({
        entityType: dto.entity_type,
        proposedName: dto.proposed_name,
        openCount: dto.open_count,
        examples,
      });
    }
  }

  const relations: ReviewData["relations"] = [];
  if (candidatesResult.ok) {
    for (const dto of candidatesResult.value) {
      relations.push({
        candidateId: dto.candidate_id,
        documentId: dto.document_id,
        relation: dto.relation,
        targetType: dto.target_type,
        targetName: dto.target_name,
        evidenceClauseId: dto.evidence_clause_id,
        evidenceQuote: dto.evidence_quote,
        quoteScore: dto.quote_score,
        confidence: dto.confidence,
        needsReview: dto.needs_review,
        issues: dto.issues,
      });
    }
  }

  return { entityGroups, relations };
}
