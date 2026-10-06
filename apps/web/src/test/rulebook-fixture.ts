import type {
  ApprovalOutDto,
  EntityDecisionOutDto,
  EntityDto,
  MentionGroupDto,
  MentionedClauseDto,
  RelationCandidateDto,
  RelationDto,
  ReviewItemDto,
  RulebookDocumentDto,
} from "@/entities/rulebook/types";

/**
 * Rulebook records for unit tests: obviously synthetic ("Example ..." text, the year 2000), never
 * regulatory content. The e2e suite reads the recorded document the seed registers instead.
 */
export const EXAMPLE_DOCUMENT_ID = "00000000-0000-0000-0000-00000000d0c1";

export const EXAMPLE_CLAUSE_IDS = {
  first: "00000000-0000-5000-8000-0000000000c1",
  second: "00000000-0000-5000-8000-0000000000c2",
  third: "00000000-0000-5000-8000-0000000000c3",
} as const;

export function documentDto(overrides: Partial<RulebookDocumentDto> = {}): RulebookDocumentDto {
  return {
    document_id: EXAMPLE_DOCUMENT_ID,
    source_id: "00000000-0000-4000-8000-000000000000",
    sha256: "0".repeat(60) + "d0c1",
    regulator: "Example regulator",
    doc_type: "circular",
    external_ref: "Example 1/2000",
    url: "https://example.com/example-document.pdf",
    title: "Example document title",
    language: "en",
    media_type: "application/pdf",
    parser_version: "example@0",
    published_at: "2000-01-15",
    // Out of order on purpose: the mapper sorts by ordinal.
    clauses: [
      {
        clause_id: EXAMPLE_CLAUSE_IDS.third,
        clause_ref: "en.p3",
        ordinal: 3,
        page: 2,
        text: "Example clause text on the second page.",
      },
      {
        clause_id: EXAMPLE_CLAUSE_IDS.first,
        clause_ref: "en.p1",
        ordinal: 1,
        page: 1,
        text: "Example clause text that opens the document.",
      },
      {
        clause_id: EXAMPLE_CLAUSE_IDS.second,
        clause_ref: "en.p2",
        ordinal: 2,
        page: null,
        text: "Example clause text without a page.",
      },
    ],
    ...overrides,
  };
}

export const EXAMPLE_ENTITY_ID = "00000000-0000-4000-8000-0000000000e1";
export const EXAMPLE_OTHER_ENTITY_ID = "00000000-0000-4000-8000-0000000000e2";

/** A canonical entity as `GET /v1/rulebook/entities/{id}` answers it. */
export function entityDto(overrides: Partial<EntityDto> = {}): EntityDto {
  return {
    entity_id: EXAMPLE_ENTITY_ID,
    entity_type: "form",
    canonical_name: "example form",
    aliases: ["example form 1", "form e"],
    ...overrides,
  };
}

/** A clause that mentions the entity twice, with its document's facts. */
export function mentionedClauseDto(
  overrides: Partial<MentionedClauseDto> = {},
): MentionedClauseDto {
  return {
    clause_id: EXAMPLE_CLAUSE_IDS.first,
    document_id: EXAMPLE_DOCUMENT_ID,
    clause_ref: "en.p1",
    ordinal: 1,
    page: 1,
    text: "Example clause names example form, then example form 1 again.",
    regulator: "Example regulator",
    doc_type: "circular",
    external_ref: "Example 1/2000",
    title: "Example document title",
    url: "https://example.com/example-document.pdf",
    language: "en",
    published_at: "2000-01-15",
    mentions: [
      { text: "example form", span_start: 21, span_end: 33 },
      { text: "example form 1", span_start: 40, span_end: 54 },
    ],
    out_of_force: false,
    ...overrides,
  };
}

/** A relation from a rule version to the entity, with its evidence clause. */
export function relationDto(overrides: Partial<RelationDto> = {}): RelationDto {
  return {
    relation_id: "00000000-0000-4000-8000-0000000000b1",
    from_rule_version_id: "00000000-0000-4000-8000-0000000000f1",
    relation: "refers_to",
    to_kind: "form",
    to_ref: "example form",
    to_rule_version_id: null,
    to_entity_id: EXAMPLE_ENTITY_ID,
    evidence_clause_id: EXAMPLE_CLAUSE_IDS.first,
    evidence_clause_ref: "en.p1",
    evidence_document_id: EXAMPLE_DOCUMENT_ID,
    candidate_id: null,
    period_label: null,
    new_due_on: null,
    ...overrides,
  };
}

// ---- The review queues: open mentions in groups, relation candidates, and decisions ----------

export const EXAMPLE_REVIEW_IDS = {
  first: "00000000-0000-4000-8000-0000000000a7",
  second: "00000000-0000-4000-8000-0000000000a8",
} as const;

export const EXAMPLE_CANDIDATE_ID = "00000000-0000-4000-8000-0000000000ca";
export const EXAMPLE_OTHER_CANDIDATE_ID = "00000000-0000-4000-8000-0000000000cb";
export const EXAMPLE_RULE_RELATION_ID = "00000000-0000-4000-8000-0000000000b9";

/** One open mention in the second clause: its first two words (code points 0 to 14). */
export function reviewItemDto(overrides: Partial<ReviewItemDto> = {}): ReviewItemDto {
  return {
    review_id: EXAMPLE_REVIEW_IDS.first,
    document_id: EXAMPLE_DOCUMENT_ID,
    clause_id: EXAMPLE_CLAUSE_IDS.second,
    mention_text: "Example clause",
    span_start: 0,
    span_end: 14,
    reason: "no_match",
    ...overrides,
  };
}

/** The group of the open mentions of the form "EXAMPLE-1", with one example. */
export function mentionGroupDto(overrides: Partial<MentionGroupDto> = {}): MentionGroupDto {
  return {
    entity_type: "form",
    proposed_name: "EXAMPLE-1",
    open_count: 2,
    examples: [reviewItemDto()],
    ...overrides,
  };
}

/** What a decision over a group answers. */
export function groupDecisionDto(
  overrides: Partial<EntityDecisionOutDto> = {},
): EntityDecisionOutDto {
  return {
    status: "resolved",
    resolution: "created",
    entity_id: EXAMPLE_ENTITY_ID,
    items_closed: 2,
    relation_targets_updated: 1,
    ...overrides,
  };
}

/** An open candidate extending a deadline of the rule "example_rule", quoting the first clause. */
export function relationCandidateDto(
  overrides: Partial<RelationCandidateDto> = {},
): RelationCandidateDto {
  return {
    candidate_id: EXAMPLE_CANDIDATE_ID,
    document_id: EXAMPLE_DOCUMENT_ID,
    relation: "extends_deadline",
    target_type: "form",
    target_name: "EXAMPLE-1",
    target_entity_id: null,
    target_rule_key: "example_rule",
    evidence_clause_id: EXAMPLE_CLAUSE_IDS.first,
    evidence_quote: "clause text that opens",
    quote_score: 1,
    period_label: "2000-01",
    new_due_on: "2000-02-21",
    prompt_version: "example.prompt@1",
    model: "example/model",
    confidence: 0.9,
    issues: [{ code: "target_unaligned", detail: "Example detail" }],
    needs_review: true,
    status: "open",
    reject_reason: null,
    decided_by: "",
    ...overrides,
  };
}

/** What approving a candidate answers. */
export function approvalDto(overrides: Partial<ApprovalOutDto> = {}): ApprovalOutDto {
  return {
    candidate_id: EXAMPLE_CANDIDATE_ID,
    rule_relation_id: EXAMPLE_RULE_RELATION_ID,
    ...overrides,
  };
}
