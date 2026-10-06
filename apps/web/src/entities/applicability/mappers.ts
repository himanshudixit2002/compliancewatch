import type {
  ChangeImpact,
  ChangeImpactDto,
  Decision,
  DecisionDto,
  ImpactBusiness,
  ImpactBusinessDto,
  PredicateOutcome,
  PredicateResultDto,
} from "./types";

export function predicateOutcomeFromDto(dto: PredicateResultDto): PredicateOutcome {
  return {
    attribute: dto.attribute,
    kind: dto.kind,
    description: dto.description,
    outcome: dto.outcome,
    confidence: dto.confidence,
    reason: dto.reason,
    needsReview: dto.needs_review,
  };
}

export function decisionFromDto(dto: DecisionDto): Decision {
  return {
    id: dto.decision_id,
    businessId: dto.business_id,
    ruleVersionId: dto.rule_version_id,
    result: dto.result,
    confidence: dto.confidence,
    needsReview: dto.needs_review,
    profileVersion: dto.profile_version,
    asOfFy: dto.as_of_fy ?? null,
    trigger: dto.trigger,
    decidedAt: dto.decided_at,
    evaluated: dto.evaluated.map(predicateOutcomeFromDto),
  };
}

export function impactBusinessFromDto(dto: ImpactBusinessDto): ImpactBusiness {
  return {
    businessId: dto.business_id,
    level: dto.level ?? null,
    decisionId: dto.decision_id,
    result: dto.result,
    confidence: dto.confidence,
    needsReview: dto.needs_review,
    decidedAt: dto.decided_at,
  };
}

export function changeImpactFromDto(dto: ChangeImpactDto): ChangeImpact {
  return {
    ruleVersionId: dto.rule_version_id,
    clients: dto.items.map((client) => ({
      entityId: client.entity_id,
      businesses: client.businesses.map(impactBusinessFromDto),
    })),
    nextCursor: dto.next_cursor ?? null,
  };
}
