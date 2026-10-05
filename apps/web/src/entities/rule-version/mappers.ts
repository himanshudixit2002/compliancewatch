import {
  NEEDS_REVIEW,
  type ActorInDto,
  type ApproveVersionInDto,
  type Citation,
  type CitationDto,
  type CitationInput,
  type CitationReport,
  type CitationsInDto,
  type CitationsOutDto,
  type LifecycleDto,
  type ObligationTemplate,
  type Publication,
  type PublicationDto,
  type Recurrence,
  type RuleDto,
  type RuleSource,
  type RuleSummary,
  type RuleVersion,
  type RuleVersionDetailDto,
  type RuleVersionDto,
  type SpecNode,
  type SpecValue,
  type SubmitInDto,
  type VersionLifecycle,
} from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSpecValue(value: unknown): value is SpecValue {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function wholeNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

const PREDICATE_KEYS = new Set(["attribute", "operator", "value", "free_text"]);

function specNode(raw: unknown): SpecNode {
  if (!isRecord(raw)) return { kind: "unreadable", raw };
  const keys = Object.keys(raw);
  if (keys.length === 1 && Array.isArray(raw.all_of)) {
    return { kind: "all_of", items: raw.all_of.map(specNode) };
  }
  if (keys.length === 1 && Array.isArray(raw.any_of)) {
    return { kind: "any_of", items: raw.any_of.map(specNode) };
  }
  if (keys.length === 1 && "not" in raw) return { kind: "not", item: specNode(raw.not) };
  if (typeof raw.attribute !== "string" || !keys.every((key) => PREDICATE_KEYS.has(key))) {
    return { kind: "unreadable", raw };
  }
  const operator = typeof raw.operator === "string" ? raw.operator : null;
  const freeText = text(raw.free_text);
  const multi = Array.isArray(raw.value);
  const values: unknown[] = Array.isArray(raw.value)
    ? raw.value
    : raw.value === undefined || raw.value === null
      ? []
      : [raw.value];
  const complete = operator === null ? values.length === 0 : values.length > 0;
  if (!values.every(isSpecValue) || !complete || (operator === null && freeText === "")) {
    return { kind: "unreadable", raw };
  }
  return { kind: "predicate", attribute: raw.attribute, operator, values, multi, freeText };
}

/**
 * The predicate tree from the kernel's mapping, or null for an empty mapping (a version that
 * states no condition yet). A node of a shape the kernel does not write is kept as unreadable.
 */
export function specificationFromMapping(raw: unknown): SpecNode | null {
  if (isRecord(raw) && Object.keys(raw).length === 0) return null;
  return specNode(raw);
}

/** The obligation template, or null when the mapping has no title (an unknown shape). */
export function obligationTemplateFromMapping(raw: unknown): ObligationTemplate | null {
  if (!isRecord(raw) || typeof raw.title !== "string") return null;
  const steps = Array.isArray(raw.steps)
    ? raw.steps.filter((step): step is string => typeof step === "string")
    : [];
  return {
    title: raw.title,
    steps,
    dueInDays: wholeNumber(raw.due_in_days),
    evidenceType: typeof raw.evidence_type === "string" ? raw.evidence_type : null,
  };
}

/** How the obligation recurs, or null for a one-off duty (or an unknown shape). */
export function recurrenceFromMapping(raw: unknown): Recurrence | null {
  if (!isRecord(raw) || typeof raw.frequency !== "string") return null;
  return {
    frequency: raw.frequency,
    dueDay: wholeNumber(raw.due_day),
    dueMonthOffset: wholeNumber(raw.due_month_offset),
  };
}

export function sourceFromMapping(raw: unknown): RuleSource {
  const source = isRecord(raw) ? raw : {};
  return {
    instrument: text(source.instrument),
    reference: text(source.reference),
    note: text(source.note),
    url: text(source.url),
  };
}

export function ruleFromDto(dto: RuleDto): RuleSummary {
  return { ruleKey: dto.rule_key, ruleId: dto.rule_id, regulator: dto.regulator, title: dto.title };
}

/** A version from the list routes or the detail route (whose citations are mapped apart). */
export function ruleVersionFromDto(dto: RuleVersionDto | RuleVersionDetailDto): RuleVersion {
  return {
    ruleVersionId: dto.rule_version_id,
    ruleId: dto.rule_id,
    ruleKey: dto.rule_key,
    regulator: dto.regulator,
    level: dto.level,
    version: dto.version,
    status: dto.status,
    title: dto.title,
    summary: dto.summary,
    specification: specificationFromMapping(dto.specification),
    obligationTemplate: obligationTemplateFromMapping(dto.obligation_template),
    recurrence: recurrenceFromMapping(dto.recurrence),
    effectiveFrom: dto.effective_from,
    effectiveTo: dto.effective_to ?? null,
    source: sourceFromMapping(dto.source),
    seedStatus: dto.seed_status,
    needsReview: dto.seed_status === NEEDS_REVIEW,
    todo: [...dto.todo],
    publishedAt: dto.published_at ?? null,
    approvedBy: "approved_by" in dto ? [...dto.approved_by] : [],
    highImpact: dto.high_impact,
    stored: {
      specification: { ...dto.specification },
      obligationTemplate: { ...dto.obligation_template },
      recurrence:
        dto.recurrence === null || dto.recurrence === undefined ? null : { ...dto.recurrence },
      source: { ...dto.source },
    },
  };
}

export function citationFromDto(dto: CitationDto): Citation {
  return {
    citationId: dto.citation_id,
    ruleVersionId: dto.rule_version_id,
    clauseId: dto.clause_id,
    documentId: dto.document_id,
    clauseRef: dto.clause_ref,
    quote: dto.quote,
    verified: dto.verified,
    matchScore: dto.match_score ?? null,
    verifiedAt: dto.verified_at ?? null,
  };
}

export function citationReportFromDto(dto: CitationsOutDto): CitationReport {
  return {
    added: dto.added,
    unchanged: dto.unchanged,
    citations: dto.citations.map(citationFromDto),
  };
}

export function lifecycleFromDto(dto: LifecycleDto): VersionLifecycle {
  return {
    ruleVersionId: dto.rule_version_id,
    ruleId: dto.rule_id,
    version: dto.version,
    status: dto.status,
    seedStatus: dto.seed_status,
    highImpact: dto.high_impact,
    effectiveFrom: dto.effective_from,
    effectiveTo: dto.effective_to ?? null,
    submittedAt: dto.submitted_at ?? null,
    publishedAt: dto.published_at ?? null,
    approvedBy: [...dto.approved_by],
    requiredApprovals: dto.required_approvals,
    events: dto.events.map((event) => ({ eventId: event.event_id, topic: event.topic })),
  };
}

export function publicationFromDto(dto: PublicationDto): Publication {
  return {
    ...lifecycleFromDto(dto),
    correlationId: dto.correlation_id,
    replacements: dto.replacements.map((replacement) => ({
      ruleVersionId: replacement.rule_version_id,
      relation: replacement.relation,
      effectiveTo: replacement.effective_to ?? null,
      status: replacement.status,
      movesTo: replacement.moves_to,
      pending: replacement.pending,
    })),
    deadlineChanges: dto.deadline_changes.map((change) => ({
      ruleVersionId: change.rule_version_id,
      periodLabel: change.period_label ?? null,
      newDueOn: change.new_due_on,
      evidenceClauseId: change.evidence_clause_id,
    })),
    attributeKeys: [...dto.attribute_keys],
  };
}

export function citationsToDto(citations: readonly CitationInput[]): CitationsInDto {
  return {
    citations: citations.map((citation) => ({
      clause_id: citation.clauseId,
      quote: citation.quote,
    })),
  };
}

/** A submission: the session's user (filled by the server layer), the high-impact tag, a note. */
export function submitToDto(
  input: { highImpact: boolean; note: string },
  actorId: string,
): SubmitInDto {
  return { actor_id: actorId, high_impact: input.highImpact, note: input.note };
}

/** Return, publish and withdraw: the session's user and the note (a reason for two of them). */
export function actorToDto(note: string, actorId: string): ActorInDto {
  return { actor_id: actorId, note };
}

/**
 * An approval as the web app sends it: the session's user and the note, nothing else. The
 * route's `synthetic` field marks an approval no analyst made, which only the local product's
 * demo tool (`cw-product`) sends; the web app never sends it, so the body type leaves it out.
 */
export function versionApprovalToDto(
  note: string,
  actorId: string,
): Omit<ApproveVersionInDto, "synthetic"> {
  return { actor_id: actorId, note };
}
