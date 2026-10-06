import type { DecisionDto, DecisionPageDto } from "@/entities/applicability/types";
import type {
  ListedObligationDto,
  ObligationChangeDto,
  ObligationCommentDto,
  ObligationDetailDto,
  ObligationDto,
  ObligationPageDto,
  RuleVersionFactsDto,
} from "@/entities/obligation/types";

/**
 * Obligation and decision bodies for unit tests: fixed synthetic ids, "Example ..." text and
 * dates in the year 2000, never a real return or rule. The e2e suite reads real ones.
 */
export const TENANT_ID = "00000000-0000-4000-8000-0000000000aa";
export const USER_ID = "00000000-0000-4000-8000-0000000000ab";
export const ENTITY_ID = "00000000-0000-4000-8000-0000000000e1";
export const REGISTRATION_ID = "00000000-0000-4000-8000-0000000000a1";
export const OBLIGATION_ID = "00000000-0000-4000-8000-0000000000b1";
export const RULE_VERSION_ID = "00000000-0000-4000-8000-0000000000d1";
export const DECISION_ID = "00000000-0000-4000-8000-0000000000d2";
export const CLAUSE_ID = "00000000-0000-5000-8000-0000000000c1";
export const DOCUMENT_ID = "00000000-0000-0000-0000-00000000d0c1";
export const APPROVER_IDS = [
  "00000000-0000-4000-8000-00000000a0a2",
  "00000000-0000-4000-8000-00000000a0a3",
] as const;

/** 10 Jan 2000, 12:00 in India: the "now" the unit tests judge due dates by. */
export const NOW = new Date("2000-01-10T06:30:00Z");

/** The end of a due day in India, as the service gives it in UTC. */
export function dueAt(day: string): string {
  return `${day}T18:29:59Z`;
}

export function obligationDto(overrides: Partial<ObligationDto> = {}): ObligationDto {
  return {
    obligation_id: OBLIGATION_ID,
    business_id: REGISTRATION_ID,
    rule_version_id: RULE_VERSION_ID,
    decision_id: DECISION_ID,
    title: "Example return 1",
    steps: ["Example step one", "Example step two"],
    evidence_type: "example_acknowledgement",
    period_label: "2000-01",
    period_start: "2000-01-01",
    period_end: "2000-02-01",
    due_at: dueAt("2000-01-20"),
    status: "open",
    closed_at: null,
    closed_reason: null,
    profile_version: 3,
    assignee_id: null,
    ...overrides,
  };
}

export function ruleVersionFactsDto(
  overrides: Partial<RuleVersionFactsDto> = {},
): RuleVersionFactsDto {
  return {
    rule_version_id: RULE_VERSION_ID,
    rule_key: "example_rule",
    title: "Example rule 1",
    status: "published",
    effective_from: "2000-01-01",
    effective_to: null,
    seed_status: "needs_review",
    reviewed: false,
    approved_by: [...APPROVER_IDS],
    published_at: "2000-01-02T04:30:00Z",
    ...overrides,
  };
}

export function listedObligationDto(
  overrides: Partial<ListedObligationDto> = {},
): ListedObligationDto {
  return {
    ...obligationDto(),
    rule_version: ruleVersionFactsDto(),
    citations: [
      {
        citation_id: "00000000-0000-4000-8000-0000000000f1",
        clause_id: CLAUSE_ID,
        document_id: DOCUMENT_ID,
        clause_ref: "en.p2",
        quote: "Example quoted clause text.",
        match_score: 1,
        verified_at: "2000-01-02T04:00:00Z",
      },
    ],
    ...overrides,
  };
}

export function obligationPageDto(
  items: ListedObligationDto[],
  nextCursor: string | null = null,
): ObligationPageDto {
  return { items, next_cursor: nextCursor };
}

export function changeDto(overrides: Partial<ObligationChangeDto> = {}): ObligationChangeDto {
  return {
    change_id: "00000000-0000-4000-8000-000000000c01",
    kind: "created",
    occurred_at: "2000-01-03T05:00:00Z",
    status_after: "open",
    reason: "",
    note: "",
    previous_due_at: null,
    new_due_at: null,
    previous_assignee_id: null,
    new_assignee_id: null,
    caused_by_rule_version_id: null,
    actor: null,
    ...overrides,
  };
}

export function commentDto(overrides: Partial<ObligationCommentDto> = {}): ObligationCommentDto {
  return {
    comment_id: "00000000-0000-4000-8000-000000000c11",
    obligation_id: OBLIGATION_ID,
    author_id: USER_ID,
    author_label: "owner",
    body: "Example comment",
    created_at: "2000-01-04T05:00:00Z",
    ...overrides,
  };
}

export function obligationDetailDto(
  overrides: Partial<ObligationDetailDto> = {},
): ObligationDetailDto {
  return {
    ...listedObligationDto(),
    history: [changeDto()],
    comments: [],
    ...overrides,
  };
}

export function decisionDto(overrides: Partial<DecisionDto> = {}): DecisionDto {
  return {
    decision_id: DECISION_ID,
    business_id: REGISTRATION_ID,
    rule_version_id: RULE_VERSION_ID,
    result: "applies",
    confidence: 1,
    needs_review: false,
    profile_version: 3,
    as_of_fy: "1999-00",
    trigger: "rule_published",
    decided_at: "2000-01-03T04:00:00Z",
    evaluated: [
      {
        attribute: "example_kind",
        kind: "structured",
        description: "Example kind is second",
        predicate: { attribute: "example_kind", operator: "eq", value: "second" },
        outcome: "applies",
        confidence: 1,
        reason: "Example kind is second on this node",
        needs_review: false,
      },
    ],
    ...overrides,
  };
}

export function decisionPageDto(items: DecisionDto[]): DecisionPageDto {
  return { items, next_cursor: null };
}
