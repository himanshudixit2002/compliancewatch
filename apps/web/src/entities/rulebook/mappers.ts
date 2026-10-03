import type {
  ApprovalOutDto,
  ApproveInDto,
  CandidateApproval,
  CandidateApproved,
  CandidateRejection,
  Clause,
  ClauseDto,
  EntityDecisionInDto,
  EntityDecisionOutDto,
  EntityGroupDecided,
  EntityGroupDecision,
  RejectInDto,
  RelationCandidate,
  RelationCandidateDto,
  RulebookDocument,
  RulebookDocumentDto,
} from "./types";

export function clauseFromDto(dto: ClauseDto): Clause {
  return {
    clauseId: dto.clause_id,
    clauseRef: dto.clause_ref,
    ordinal: dto.ordinal,
    page: dto.page ?? null,
    text: dto.text,
  };
}

/** The document with its clauses sorted by ordinal, whatever order they arrived in. */
export function documentFromDto(dto: RulebookDocumentDto): RulebookDocument {
  return {
    documentId: dto.document_id,
    sourceId: dto.source_id,
    sha256: dto.sha256,
    regulator: dto.regulator,
    docType: dto.doc_type,
    externalRef: dto.external_ref,
    url: dto.url,
    title: dto.title,
    language: dto.language,
    mediaType: dto.media_type,
    parserVersion: dto.parser_version,
    publishedAt: dto.published_at ?? null,
    clauses: dto.clauses.map(clauseFromDto).sort((a, b) => a.ordinal - b.ordinal),
  };
}

/** The decision body; `decidedBy` is the session's user, supplied by the server layer. */
export function entityDecisionToDto(
  decision: EntityGroupDecision,
  decidedBy: string,
): EntityDecisionInDto {
  return {
    entity_type: decision.entityType,
    proposed_name: decision.proposedName,
    decision: decision.decision,
    decided_by: decidedBy,
    note: decision.note,
    ...(decision.entityId === undefined ? {} : { entity_id: decision.entityId }),
    ...(decision.rejectReason === undefined ? {} : { reject_reason: decision.rejectReason }),
    ...(decision.reviewIds === undefined ? {} : { review_ids: [...decision.reviewIds] }),
  };
}

export function entityDecidedFromDto(dto: EntityDecisionOutDto): EntityGroupDecided {
  return {
    status: dto.status,
    resolution: dto.resolution ?? null,
    entityId: dto.entity_id ?? null,
    itemsClosed: dto.items_closed,
    relationTargetsUpdated: dto.relation_targets_updated,
  };
}

export function approvalToDto(approval: CandidateApproval, decidedBy: string): ApproveInDto {
  return {
    from_rule_version_id: approval.fromRuleVersionId,
    decided_by: decidedBy,
    note: approval.note,
    ...(approval.targetRuleVersionId === undefined
      ? {}
      : { target_rule_version_id: approval.targetRuleVersionId }),
  };
}

export function approvedFromDto(dto: ApprovalOutDto): CandidateApproved {
  return { candidateId: dto.candidate_id, ruleRelationId: dto.rule_relation_id };
}

export function rejectionToDto(rejection: CandidateRejection, decidedBy: string): RejectInDto {
  return { reason: rejection.reason, decided_by: decidedBy, note: rejection.note };
}

export function relationCandidateFromDto(dto: RelationCandidateDto): RelationCandidate {
  return {
    candidateId: dto.candidate_id,
    documentId: dto.document_id,
    relation: dto.relation,
    targetType: dto.target_type,
    targetName: dto.target_name,
    targetEntityId: dto.target_entity_id ?? null,
    targetRuleKey: dto.target_rule_key ?? null,
    evidenceClauseId: dto.evidence_clause_id,
    evidenceQuote: dto.evidence_quote,
    quoteScore: dto.quote_score,
    periodLabel: dto.period_label ?? null,
    newDueOn: dto.new_due_on ?? null,
    promptVersion: dto.prompt_version,
    model: dto.model,
    confidence: dto.confidence,
    issues: dto.issues.map((issue) => ({ code: issue.code, detail: issue.detail ?? "" })),
    needsReview: dto.needs_review,
    status: dto.status,
    rejectReason: dto.reject_reason ?? null,
    decidedBy: dto.decided_by,
  };
}
