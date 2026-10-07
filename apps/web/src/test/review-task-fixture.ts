import type {
  AuditEntryDto,
  QueuedTaskDto,
  ReviewStatsDto,
  ReviewTaskDetailDto,
  ReviewTaskDto,
  RuleCandidateDto,
  SeedTasksDto,
  TaskDecisionDto,
  TaskDocumentDto,
  TaskPageDto,
} from "@/entities/rule-version/types";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "./rulebook-fixture";
import {
  EXAMPLE_ANALYST_ID,
  EXAMPLE_VERSION_ID,
  citationDto,
  lifecycleDto,
  ruleVersionDto,
} from "./rule-version-fixture";

/**
 * The rulebook's review tasks for unit tests, recorded in the shapes of its spec: obviously
 * synthetic ("Example ..." text, the year 2000, zero ids), never a rule of the seed calendar or a
 * candidate a model extracted. The e2e suite reads the stack's own tasks instead.
 */
export const EXAMPLE_TASK_ID = "00000000-0000-4000-8000-0000000007a1";
export const EXAMPLE_NEXT_TASK_ID = "00000000-0000-4000-8000-0000000007a2";
export const EXAMPLE_CANDIDATE_TASK_ID = "00000000-0000-4000-8000-0000000007a3";
export const EXAMPLE_RULE_CANDIDATE_ID = "00000000-0000-4000-8000-0000000007c1";
export const EXAMPLE_RELATION_CANDIDATE_ID = "00000000-0000-4000-8000-0000000007c2";
export const EXAMPLE_REVIEWER_ID = "00000000-0000-5000-8000-0000000000b3";

export function reviewTaskDto(overrides: Partial<ReviewTaskDto> = {}): ReviewTaskDto {
  return {
    task_id: EXAMPLE_TASK_ID,
    rule_version_id: EXAMPLE_VERSION_ID,
    kind: "seed",
    candidate_id: null,
    priority: 50,
    regulator: "example_regulator",
    status: "open",
    opened_at: "2000-05-01T04:30:00Z",
    claimed_by: null,
    claimed_at: null,
    decision: null,
    decided_by: null,
    decided_at: null,
    note: "",
    ...overrides,
  };
}

export function queuedTaskDto(overrides: Partial<QueuedTaskDto> = {}): QueuedTaskDto {
  return {
    ...reviewTaskDto(),
    rule_key: "example_rule",
    version: 1,
    title: "Example rule title",
    version_status: "draft",
    high_impact: false,
    approvals: 0,
    required_approvals: 1,
    candidate: null,
    ...overrides,
  };
}

/** A candidate task not drafted yet, as the queue lists it. */
export function queuedCandidateTaskDto(overrides: Partial<QueuedTaskDto> = {}): QueuedTaskDto {
  return queuedTaskDto({
    task_id: EXAMPLE_CANDIDATE_TASK_ID,
    rule_version_id: null,
    kind: "candidate",
    candidate_id: EXAMPLE_RULE_CANDIDATE_ID,
    priority: 80,
    rule_key: "example_suggested_rule",
    version: null,
    title: "Example candidate title",
    version_status: null,
    high_impact: true,
    required_approvals: 2,
    candidate: {
      candidate_id: EXAMPLE_RULE_CANDIDATE_ID,
      document_id: EXAMPLE_DOCUMENT_ID,
      status: "open",
      outcome: "extracted",
      confidence: 0.82,
      needs_review: true,
      issue_count: 2,
      suggested_rule_key: "example_suggested_rule",
      high_impact_suggested: true,
    },
    ...overrides,
  });
}

export function taskPageDto(
  items: QueuedTaskDto[] = [queuedTaskDto()],
  nextCursor: string | null = null,
): TaskPageDto {
  return { items, next_cursor: nextCursor };
}

export function taskDocumentDto(overrides: Partial<TaskDocumentDto> = {}): TaskDocumentDto {
  return {
    document_id: EXAMPLE_DOCUMENT_ID,
    regulator: "Example regulator",
    doc_type: "circular",
    external_ref: "Example 1/2000",
    title: "Example document title",
    url: "https://example.com/example-document.pdf",
    published_at: "2000-01-15",
    ...overrides,
  };
}

export function auditEntryDto(overrides: Partial<AuditEntryDto> = {}): AuditEntryDto {
  return {
    decision_id: "00000000-0000-4000-8000-0000000007d1",
    action: "edited",
    from_status: "draft",
    to_status: "draft",
    actor_id: EXAMPLE_ANALYST_ID,
    caused_by_rule_version_id: null,
    note: "Example note: title",
    decided_at: "2000-05-01T05:00:00Z",
    ...overrides,
  };
}

/** A seed task's detail: a draft citing one clause of the example document. */
export function reviewTaskDetailDto(
  overrides: Partial<ReviewTaskDetailDto> = {},
): ReviewTaskDetailDto {
  return {
    task: reviewTaskDto(),
    rule_version: ruleVersionDto(),
    specification_described: ["all of:", "  example_kind = first"],
    citations: [citationDto()],
    documents: [taskDocumentDto()],
    source_url: null,
    approved_by: [],
    required_approvals: 1,
    decisions: [auditEntryDto()],
    tasks: [reviewTaskDto()],
    candidate: null,
    ...overrides,
  };
}

/** A rule candidate the pipeline extracted, as a candidate task's detail carries it. */
export function ruleCandidateDto(overrides: Partial<RuleCandidateDto> = {}): RuleCandidateDto {
  return {
    candidate_id: EXAMPLE_RULE_CANDIDATE_ID,
    document_id: EXAMPLE_DOCUMENT_ID,
    document: taskDocumentDto(),
    regulator: "example_regulator",
    model: "example/model",
    prompt_version: "example.extraction@1",
    confidence: 0.82,
    citation_count: 1,
    needs_review: true,
    outcome: "extracted",
    status: "open",
    reject_reason: null,
    rule_version_id: null,
    suggested_rule_key: "example_suggested_rule",
    suggested_rule_known: false,
    high_impact_suggested: true,
    high_impact_reasons: ["Example reason it looks high impact"],
    candidate: { title: "Example candidate title" },
    issues: [
      {
        code: "example_issue",
        detail: "Example detail of what the check found.",
        clause_ref: "en.p2",
      },
    ],
    clause_ids: [EXAMPLE_CLAUSE_IDS.first],
    doc_type: "circular",
    source_key: "example_source",
    ontology_version: "0.0.1",
    proposed: {
      title: "Example candidate title",
      summary: "Example summary the candidate proposes.",
      specification: { all_of: [{ attribute: "example_kind", operator: "eq", value: "second" }] },
      obligation_template: {
        title: "Example obligation",
        steps: ["Example first step"],
        due_in_days: 30,
        evidence_type: "",
      },
      recurrence: null,
      effective_from: "2000-04-01",
      effective_to: null,
      citations: [
        {
          clause_ref: "en.p1",
          clause_id: EXAMPLE_CLAUSE_IDS.first,
          quote: "Example clause text that opens",
        },
      ],
      problems: ["effective_to: Example problem the analyst fixes"],
    },
    event_id: "00000000-0000-4000-8000-0000000007e1",
    created_at: "2000-05-01T04:00:00Z",
    decided_by: null,
    decided_at: null,
    ...overrides,
  };
}

/** A candidate task's detail before drafting: no version yet, the candidate's document. */
export function candidateTaskDetailDto(
  overrides: Partial<ReviewTaskDetailDto> = {},
): ReviewTaskDetailDto {
  return reviewTaskDetailDto({
    task: reviewTaskDto({
      task_id: EXAMPLE_CANDIDATE_TASK_ID,
      rule_version_id: null,
      kind: "candidate",
      candidate_id: EXAMPLE_RULE_CANDIDATE_ID,
      priority: 80,
    }),
    rule_version: null,
    specification_described: [],
    citations: [],
    documents: [],
    required_approvals: 2,
    decisions: [],
    tasks: [
      reviewTaskDto({
        task_id: EXAMPLE_CANDIDATE_TASK_ID,
        rule_version_id: null,
        kind: "candidate",
        candidate_id: EXAMPLE_RULE_CANDIDATE_ID,
      }),
    ],
    candidate: ruleCandidateDto(),
    ...overrides,
  });
}

export function taskDecisionDto(overrides: Partial<TaskDecisionDto> = {}): TaskDecisionDto {
  return {
    task: reviewTaskDto({
      status: "decided",
      decision: "approve",
      decided_by: EXAMPLE_ANALYST_ID,
      decided_at: "2000-05-02T06:00:00Z",
    }),
    version: lifecycleDto({
      status: "approved",
      seed_status: "reviewed",
      high_impact: false,
      required_approvals: 1,
    }),
    next_task_id: null,
    candidate_status: null,
    events: [],
    ...overrides,
  };
}

export function seedTasksDto(overrides: Partial<SeedTasksDto> = {}): SeedTasksDto {
  return { opened: 2, task_ids: [EXAMPLE_TASK_ID, EXAMPLE_NEXT_TASK_ID], ...overrides };
}

export function reviewStatsDto(overrides: Partial<ReviewStatsDto> = {}): ReviewStatsDto {
  return {
    by_status: { open: 3, claimed: 1, decided: 4 },
    by_regulator: [
      { regulator: "example_regulator", open: 2, claimed: 1, decided: 4 },
      { regulator: "example_other", open: 1, claimed: 0, decided: 0 },
    ],
    decisions: { approved: 2, returned: 1, rejected: 1 },
    median_seconds_to_decide: 5400,
    oldest_open_at: "2000-05-01T04:30:00Z",
    oldest_open_age_seconds: 93_600,
    candidates: {
      decided: 3,
      approved: 2,
      approved_without_edits: 1,
      rejected: 1,
      acceptance_rate: 1 / 3,
    },
    ...overrides,
  };
}
