import type { RuleChange, RuleChangeDto, RuleChangePage, RuleChangePageDto } from "./types";

export function ruleChangeFromDto(dto: RuleChangeDto): RuleChange {
  return {
    id: dto.change_id,
    kind: dto.kind,
    changedAt: dto.changed_at,
    ruleVersionId: dto.rule_version_id,
    ruleKey: dto.rule_key,
    title: dto.title,
    summary: dto.summary,
    version: dto.version,
    regulator: dto.regulator,
    level: dto.level,
    status: dto.status,
    effectiveFrom: dto.effective_from,
    effectiveTo: dto.effective_to ?? null,
    seedStatus: dto.seed_status,
    approvedBy: [...dto.approved_by],
    publishedAt: dto.published_at ?? null,
    citations: dto.citations.map((citation) => ({
      clauseId: citation.clause_id,
      documentId: citation.document_id,
      clauseRef: citation.clause_ref,
      quote: citation.quote,
    })),
    causedByRuleVersionId: dto.caused_by_rule_version_id ?? null,
    deadline:
      dto.deadline === null
        ? null
        : {
            periodLabel: dto.deadline.period_label ?? null,
            newDueOn: dto.deadline.new_due_on ?? null,
            evidenceClauseId: dto.deadline.evidence_clause_id ?? null,
          },
    relations: {
      supersedes: [...dto.relations.supersedes],
      corrects: [...dto.relations.corrects],
      withdraws: [...dto.relations.withdraws],
      extendsDeadline: dto.relations.extends_deadline.map((extension) => ({
        ruleVersionId: extension.rule_version_id,
        periodLabel: extension.period_label ?? null,
        newDueOn: extension.new_due_on ?? null,
      })),
    },
  };
}

export function ruleChangePageFromDto(dto: RuleChangePageDto): RuleChangePage {
  return {
    items: dto.items.map(ruleChangeFromDto),
    nextCursor: dto.next_cursor ?? null,
  };
}
