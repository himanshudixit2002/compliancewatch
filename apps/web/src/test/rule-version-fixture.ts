import type {
  CitationDto,
  LifecycleDto,
  PublicationDto,
  RuleDto,
  RuleVersionDetailDto,
  RuleVersionDto,
} from "@/entities/rule-version/types";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "./rulebook-fixture";

/**
 * Rule versions for unit tests: obviously synthetic ("Example ..." text, the year 2000, example
 * attributes), never a rule of the seed calendar. The e2e suite reads the drafts the rulebook
 * loads at start instead.
 */
export const EXAMPLE_RULE_ID = "00000000-0000-4000-8000-0000000000a1";
export const EXAMPLE_VERSION_ID = "00000000-0000-4000-8000-0000000000f1";
export const EXAMPLE_OTHER_VERSION_ID = "00000000-0000-4000-8000-0000000000f2";
export const EXAMPLE_ANALYST_ID = "00000000-0000-5000-8000-0000000000b1";
export const EXAMPLE_OTHER_ANALYST_ID = "00000000-0000-5000-8000-0000000000b2";
export const EXAMPLE_CITATION_ID = "00000000-0000-4000-8000-0000000000c9";

export function ruleDto(overrides: Partial<RuleDto> = {}): RuleDto {
  return {
    rule_key: "example_rule",
    rule_id: EXAMPLE_RULE_ID,
    regulator: "example_regulator",
    title: "Example rule title",
    ...overrides,
  };
}

export function ruleVersionDto(overrides: Partial<RuleVersionDto> = {}): RuleVersionDto {
  return {
    rule_version_id: EXAMPLE_VERSION_ID,
    rule_id: EXAMPLE_RULE_ID,
    rule_key: "example_rule",
    regulator: "example_regulator",
    level: "registration",
    version: 1,
    status: "draft",
    title: "Example rule title",
    summary: "Example summary of what the rule asks.",
    // Attributes of the synthetic ontology fixture (src/test/ontology-fixture.ts), one not in it.
    specification: {
      all_of: [
        { attribute: "example_kind", operator: "eq", value: "first" },
        { attribute: "example_band", operator: "gt", value: "small" },
        {
          not: { attribute: "state_codes", operator: "contains_any", value: ["01", "02"] },
        },
        { attribute: "example_question", free_text: "Example condition an analyst judges." },
      ],
    },
    obligation_template: {
      title: "Example obligation",
      steps: ["Example first step", "Example second step"],
      due_in_days: null,
      evidence_type: "example_evidence",
    },
    recurrence: { frequency: "monthly", due_day: 20, due_month_offset: 0 },
    effective_from: "2000-04-01",
    effective_to: null,
    source: {
      instrument: "Example instrument, 2000",
      reference: "Example reference 1(1)",
      note: "Example note on the source.",
      url: "",
    },
    seed_status: "needs_review",
    todo: ["Example question for the analyst?"],
    published_at: null,
    high_impact: false,
    ...overrides,
  };
}

export function citationDto(overrides: Partial<CitationDto> = {}): CitationDto {
  return {
    citation_id: EXAMPLE_CITATION_ID,
    rule_version_id: EXAMPLE_VERSION_ID,
    clause_id: EXAMPLE_CLAUSE_IDS.first,
    document_id: EXAMPLE_DOCUMENT_ID,
    clause_ref: "en.p1",
    quote: "Example clause text that opens",
    verified: true,
    match_score: 0.97,
    verified_at: "2000-05-01T06:30:00Z",
    ...overrides,
  };
}

export function ruleVersionDetailDto(
  overrides: Partial<RuleVersionDetailDto> = {},
): RuleVersionDetailDto {
  return { ...ruleVersionDto(), approved_by: [], citations: [citationDto()], ...overrides };
}

export function lifecycleDto(overrides: Partial<LifecycleDto> = {}): LifecycleDto {
  return {
    rule_version_id: EXAMPLE_VERSION_ID,
    rule_id: EXAMPLE_RULE_ID,
    version: 1,
    status: "in_review",
    seed_status: "needs_review",
    high_impact: true,
    effective_from: "2000-04-01",
    effective_to: null,
    submitted_at: "2000-05-01T06:00:00Z",
    published_at: null,
    approved_by: [EXAMPLE_ANALYST_ID],
    required_approvals: 2,
    events: [],
    ...overrides,
  };
}

export function publicationDto(overrides: Partial<PublicationDto> = {}): PublicationDto {
  return {
    ...lifecycleDto({
      status: "published",
      seed_status: "reviewed",
      published_at: "2000-05-02T06:00:00Z",
      approved_by: [EXAMPLE_ANALYST_ID, EXAMPLE_OTHER_ANALYST_ID],
      events: [
        {
          event_id: "00000000-0000-4000-8000-0000000000e1",
          topic: "rule.published",
          correlation_id: "00000000-0000-4000-8000-0000000000e2",
          causation_id: null,
        },
      ],
    }),
    correlation_id: "00000000-0000-4000-8000-0000000000e2",
    replacements: [
      {
        rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        relation: "supersedes",
        effective_to: "2000-04-01",
        status: "published",
        moves_to: "superseded",
        pending: true,
      },
    ],
    deadline_changes: [],
    attribute_keys: ["example_band", "example_kind"],
    ...overrides,
  };
}
