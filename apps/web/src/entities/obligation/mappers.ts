import type {
  ListedObligation,
  ListedObligationDto,
  Obligation,
  ObligationChange,
  ObligationChangeDto,
  ObligationCitation,
  ObligationCitationDto,
  ObligationComment,
  ObligationCommentDto,
  ObligationDetail,
  ObligationDetailDto,
  ObligationDto,
  ObligationPage,
  ObligationPageDto,
  RuleVersionFacts,
  RuleVersionFactsDto,
  StatusChange,
  StatusInDto,
} from "./types";

/** The obligation service's bodies to the domain shapes, and a status change to its body. */
export function obligationFromDto(dto: ObligationDto): Obligation {
  return {
    id: dto.obligation_id,
    businessId: dto.business_id,
    ruleVersionId: dto.rule_version_id,
    decisionId: dto.decision_id,
    title: dto.title,
    steps: [...dto.steps],
    evidenceType: dto.evidence_type,
    periodLabel: dto.period_label ?? null,
    periodStart: dto.period_start ?? null,
    periodEnd: dto.period_end ?? null,
    dueAt: dto.due_at ?? null,
    status: dto.status,
    closedAt: dto.closed_at ?? null,
    closedReason: dto.closed_reason ?? null,
    profileVersion: dto.profile_version ?? null,
    assigneeId: dto.assignee_id ?? null,
  };
}

export function ruleVersionFactsFromDto(dto: RuleVersionFactsDto): RuleVersionFacts {
  return {
    ruleVersionId: dto.rule_version_id,
    ruleKey: dto.rule_key,
    title: dto.title,
    status: dto.status,
    effectiveFrom: dto.effective_from,
    effectiveTo: dto.effective_to ?? null,
    seedStatus: dto.seed_status,
    reviewed: dto.reviewed,
    approvedBy: [...dto.approved_by],
    publishedAt: dto.published_at ?? null,
  };
}

export function obligationCitationFromDto(dto: ObligationCitationDto): ObligationCitation {
  return {
    citationId: dto.citation_id,
    clauseId: dto.clause_id,
    documentId: dto.document_id,
    clauseRef: dto.clause_ref,
    quote: dto.quote,
    matchScore: dto.match_score ?? null,
    verifiedAt: dto.verified_at ?? null,
  };
}

export function listedObligationFromDto(dto: ListedObligationDto): ListedObligation {
  return {
    ...obligationFromDto(dto),
    ruleVersion: dto.rule_version === null ? null : ruleVersionFactsFromDto(dto.rule_version),
    citations: dto.citations.map(obligationCitationFromDto),
  };
}

export function obligationPageFromDto(dto: ObligationPageDto): ObligationPage {
  return {
    items: dto.items.map(listedObligationFromDto),
    nextCursor: dto.next_cursor ?? null,
  };
}

export function obligationChangeFromDto(dto: ObligationChangeDto): ObligationChange {
  return {
    id: dto.change_id,
    kind: dto.kind,
    occurredAt: dto.occurred_at,
    statusAfter: dto.status_after,
    reason: dto.reason,
    note: dto.note,
    previousDueAt: dto.previous_due_at ?? null,
    newDueAt: dto.new_due_at ?? null,
    previousAssigneeId: dto.previous_assignee_id ?? null,
    newAssigneeId: dto.new_assignee_id ?? null,
    causedByRuleVersionId: dto.caused_by_rule_version_id ?? null,
    actor: dto.actor ?? null,
  };
}

export function obligationCommentFromDto(dto: ObligationCommentDto): ObligationComment {
  return {
    id: dto.comment_id,
    obligationId: dto.obligation_id,
    authorId: dto.author_id ?? null,
    authorLabel: dto.author_label,
    body: dto.body,
    createdAt: dto.created_at,
  };
}

export function obligationDetailFromDto(dto: ObligationDetailDto): ObligationDetail {
  return {
    ...obligationFromDto(dto),
    ruleVersion: dto.rule_version === null ? null : ruleVersionFactsFromDto(dto.rule_version),
    citations: dto.citations.map(obligationCitationFromDto),
    history: dto.history.map(obligationChangeFromDto),
    comments: dto.comments.map(obligationCommentFromDto),
  };
}

/** The body of a status change: the reason travels only with a waiver, trimmed. */
export function statusChangeToDto(change: StatusChange): StatusInDto {
  return change.action === "waive"
    ? { action: change.action, reason: change.reason.trim() }
    : { action: change.action };
}
