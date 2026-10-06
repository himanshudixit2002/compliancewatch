import type {
  AttributeCounts,
  ChangeImpact,
  ChangeImpactDto,
  Decision,
  DecisionDto,
  DryRunInDto,
  DryRunOutDto,
  DryRunReport,
  DryRunRequest,
  DryRunSample,
  DryRunSampleDto,
  FanOutHold,
  FanOutHoldDto,
  FanOutHoldInDto,
  FanOutRun,
  FanOutRunDto,
  FanOutRunPage,
  FanOutRunPageDto,
  ImpactBusiness,
  ImpactBusinessDto,
  ImpactFanOut,
  PredicateOutcome,
  PredicateResultDto,
  ResolveDto,
  ResolveInput,
  ResultCounts,
  ReviewItem,
  ReviewItemDto,
  ReviewItemPage,
  ReviewItemPageDto,
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

export function resultCountsFromDto(dto: {
  applies: number;
  not_applicable: number;
  unsure: number;
}): ResultCounts {
  return { applies: dto.applies, notApplicable: dto.not_applicable, unsure: dto.unsure };
}

function impactFanOutFromDto(dto: NonNullable<ChangeImpactDto["fan_out"]>): ImpactFanOut {
  return {
    status: dto.status,
    businessesTotal: dto.businesses_total,
    evaluated: dto.evaluated,
    applies: dto.applies,
    startedAt: dto.started_at,
    updatedAt: dto.updated_at,
    finishedAt: dto.finished_at ?? null,
  };
}

export function changeImpactFromDto(dto: ChangeImpactDto): ChangeImpact {
  return {
    ruleVersionId: dto.rule_version_id,
    counts: resultCountsFromDto(dto.counts),
    fanOut:
      dto.fan_out === null || dto.fan_out === undefined ? null : impactFanOutFromDto(dto.fan_out),
    clients: dto.items.map((client) => ({
      entityId: client.entity_id,
      businesses: client.businesses.map(impactBusinessFromDto),
    })),
    nextCursor: dto.next_cursor ?? null,
  };
}

// ---- The review queue -----------------------------------------------------------------------

export function reviewItemFromDto(dto: ReviewItemDto): ReviewItem {
  return {
    id: dto.item_id,
    businessId: dto.business_id,
    ruleVersionId: dto.rule_version_id,
    reason: dto.reason,
    status: dto.status,
    openedAt: dto.opened_at,
    decision: decisionFromDto(dto.decision),
    resolution: dto.resolution ?? null,
    resolvedBy: dto.resolved_by ?? null,
    resolvedAt: dto.resolved_at ?? null,
    note: dto.note,
    resolutionDecisionId: dto.resolution_decision_id ?? null,
  };
}

export function reviewItemPageFromDto(dto: ReviewItemPageDto): ReviewItemPage {
  return { items: dto.items.map(reviewItemFromDto), nextCursor: dto.next_cursor ?? null };
}

/** A resolution as the engine takes it; the reviewer is the session's user, filled by the caller. */
export function resolveToDto(input: ResolveInput, resolvedBy: string): ResolveDto {
  return { resolution: input.resolution, note: input.note, resolved_by: resolvedBy };
}

// ---- Fan-outs and the hold ------------------------------------------------------------------

export function fanOutRunFromDto(dto: FanOutRunDto): FanOutRun {
  return {
    ruleVersionId: dto.rule_version_id,
    ruleKey: dto.rule_key,
    level: dto.level,
    status: dto.status,
    triggerEventId: dto.trigger_event_id,
    supersedes: dto.supersedes,
    businessesTotal: dto.businesses_total,
    evaluated: dto.evaluated,
    applies: dto.applies,
    flipsCompared: dto.flips_compared,
    flips: dto.flips,
    flipRate: dto.flip_rate ?? null,
    startedAt: dto.started_at,
    updatedAt: dto.updated_at,
    finishedAt: dto.finished_at ?? null,
    statusReason: dto.status_reason,
    statusBy: dto.status_by,
    lastError: dto.last_error,
  };
}

export function fanOutPageFromDto(dto: FanOutRunPageDto): FanOutRunPage {
  return { items: dto.items.map(fanOutRunFromDto), nextCursor: dto.next_cursor ?? null };
}

export function fanOutHoldFromDto(dto: FanOutHoldDto): FanOutHold {
  return {
    held: dto.held,
    reason: dto.reason ?? null,
    setBy: dto.set_by ?? null,
    setAt: dto.set_at ?? null,
  };
}

/** Setting the hold needs a reason; releasing takes one if given. */
export function holdToDto(held: boolean, reason: string): FanOutHoldInDto {
  return { held, reason };
}

// ---- Dry runs ---------------------------------------------------------------------------------

export function dryRunToDto(request: DryRunRequest): DryRunInDto {
  const scope = {
    sample_size: request.sampleSize,
    ...(request.level === null ? {} : { level: request.level }),
    ...(request.tenantId === null ? {} : { tenant_id: request.tenantId }),
  };
  return request.ruleVersionId !== null
    ? { rule_version_id: request.ruleVersionId, scope }
    : { specification: { ...request.specification }, scope };
}

function attributeCountsFromDto(dto: DryRunOutDto["by_attribute"][number]): AttributeCounts {
  return { attribute: dto.attribute, ...resultCountsFromDto(dto) };
}

function dryRunSampleFromDto(dto: DryRunSampleDto): DryRunSample {
  return {
    tenantId: dto.tenant_id,
    businessId: dto.business_id,
    profileVersion: dto.profile_version,
    result: dto.result,
    confidence: dto.confidence,
    needsReview: dto.needs_review,
    deciding: dto.deciding,
    evaluated: dto.evaluated.map(predicateOutcomeFromDto),
  };
}

export function dryRunReportFromDto(dto: DryRunOutDto): DryRunReport {
  return {
    ruleVersionId: dto.rule_version_id ?? null,
    ruleKey: dto.rule_key ?? null,
    status: dto.status ?? null,
    level: dto.level,
    tenantId: dto.tenant_id ?? null,
    asOfFy: dto.as_of_fy,
    businessesTotal: dto.businesses_total,
    evaluated: dto.evaluated,
    skipped: dto.skipped,
    counts: resultCountsFromDto(dto.counts),
    needsReview: dto.needs_review,
    byAttribute: dto.by_attribute.map(attributeCountsFromDto),
    samples: dto.samples.map(dryRunSampleFromDto),
    maxBusinesses: dto.max_businesses,
    ranAt: dto.ran_at,
  };
}
