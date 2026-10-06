import type {
  ApprovalOutDto,
  ApproveInDto,
  CandidateApproval,
  CandidateApproved,
  CandidateRejection,
  CanonicalEntity,
  Clause,
  ClauseDetail,
  ClauseDetailDto,
  ClauseDto,
  EntityDecisionInDto,
  EntityDecisionOutDto,
  EntityDto,
  EntityGroupDecided,
  EntityGroupDecision,
  EntityResolution,
  EntityResolutionDto,
  MentionGroup,
  MentionGroupDto,
  MentionedClause,
  MentionedClauseDto,
  RejectInDto,
  RelationCandidate,
  RelationCandidateDto,
  RelationDto,
  ReviewItem,
  ReviewItemDto,
  RuleRelation,
  RulebookDocument,
  RulebookDocumentDto,
  SearchHit,
  SearchHitDto,
  SearchInDto,
  SearchQuery,
} from "./types";

export function reviewItemFromDto(dto: ReviewItemDto): ReviewItem {
  return {
    reviewId: dto.review_id,
    documentId: dto.document_id,
    clauseId: dto.clause_id,
    mentionText: dto.mention_text,
    spanStart: dto.span_start,
    spanEnd: dto.span_end,
    reason: dto.reason,
  };
}

export function mentionGroupFromDto(dto: MentionGroupDto): MentionGroup {
  return {
    entityType: dto.entity_type,
    proposedName: dto.proposed_name,
    openCount: dto.open_count,
    examples: dto.examples.map(reviewItemFromDto),
  };
}

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

export function entityFromDto(dto: EntityDto): CanonicalEntity {
  return {
    entityId: dto.entity_id,
    entityType: dto.entity_type,
    canonicalName: dto.canonical_name,
    aliases: [...dto.aliases],
  };
}

export function resolutionFromDto(dto: EntityResolutionDto): EntityResolution {
  return {
    status: dto.status,
    entityType: dto.entity_type,
    name: dto.name,
    normalised: dto.normalised,
    entity: dto.entity === null || dto.entity === undefined ? null : entityFromDto(dto.entity),
    candidates: dto.candidates.map(entityFromDto),
  };
}

export function clauseDetailFromDto(dto: ClauseDetailDto): ClauseDetail {
  return {
    clauseId: dto.clause_id,
    documentId: dto.document_id,
    clauseRef: dto.clause_ref,
    ordinal: dto.ordinal,
    page: dto.page ?? null,
    text: dto.text,
    regulator: dto.regulator,
    docType: dto.doc_type,
    externalRef: dto.external_ref,
    title: dto.title,
    url: dto.url,
    language: dto.language,
    publishedAt: dto.published_at ?? null,
  };
}

export function mentionedClauseFromDto(dto: MentionedClauseDto): MentionedClause {
  return {
    ...clauseDetailFromDto(dto),
    mentions: dto.mentions.map((mention) => ({
      text: mention.text,
      start: mention.span_start,
      end: mention.span_end,
    })),
    outOfForce: dto.out_of_force,
  };
}

export function relationFromDto(dto: RelationDto): RuleRelation {
  return {
    relationId: dto.relation_id,
    fromRuleVersionId: dto.from_rule_version_id,
    relation: dto.relation,
    toKind: dto.to_kind,
    toRef: dto.to_ref,
    toRuleVersionId: dto.to_rule_version_id ?? null,
    toEntityId: dto.to_entity_id ?? null,
    evidenceClauseId: dto.evidence_clause_id,
    evidenceClauseRef: dto.evidence_clause_ref,
    evidenceDocumentId: dto.evidence_document_id,
    candidateId: dto.candidate_id ?? null,
    periodLabel: dto.period_label ?? null,
    newDueOn: dto.new_due_on ?? null,
  };
}

/** The search body: text only, so the vector leg runs only for a caller that sends a vector. */
export function searchToDto(query: SearchQuery): SearchInDto {
  return {
    text: query.text,
    k: query.k,
    doc_types: [...query.docTypes],
    ...(query.regulator === undefined ? {} : { regulator: query.regulator }),
    ...(query.asOf === undefined ? {} : { as_of: query.asOf }),
  };
}

export function searchHitFromDto(dto: SearchHitDto): SearchHit {
  return {
    clauseId: dto.clause_id,
    documentId: dto.document_id,
    clauseRef: dto.clause_ref,
    text: dto.text,
    regulator: dto.regulator,
    docType: dto.doc_type,
    externalRef: dto.external_ref,
    title: dto.title,
    publishedAt: dto.published_at ?? null,
    score: dto.score,
    lexicalRank: dto.lexical_rank ?? null,
    vectorRank: dto.vector_rank ?? null,
    citedBy: [...dto.cited_by],
    outOfForce: dto.out_of_force,
  };
}
