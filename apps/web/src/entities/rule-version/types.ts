import type { rulebook } from "@compliancewatch/contracts/openapi";
import { membersOf } from "@/shared/lib/union";

/**
 * Rules and their versions as the rulebook service keeps them (ADR-006): a rule (`rule_key`) has
 * numbered versions, each one moving draft, in_review, approved, published, then superseded or
 * withdrawn. A version carries its applicability condition (`specification`, the kernel's
 * predicate tree), the obligation it creates, how the obligation recurs, its effective period,
 * the cited instrument, the questions an analyst answers before publication (`todo`) and whether
 * an analyst has reviewed it (`seed_status`). Citations tie it to the clauses it rests on.
 *
 * The wire shapes are the rulebook spec's. The specification, the obligation template, the
 * recurrence and the source are open mappings on the wire; the mappers read the keys the kernel
 * writes and keep anything else visible rather than guessing.
 */
type Schemas = rulebook.components["schemas"];

export type RuleVersionStatus = Schemas["RuleVersionStatus"];
export type SeedStatus = Schemas["SeedStatus"];
export type VersionLevel = Schemas["AttributeLevel"];

export type RuleDto = Schemas["RuleOut"];
export type RuleVersionDto = Schemas["RuleVersionOut"];
export type RuleVersionDetailDto = Schemas["RuleVersionDetailOut"];
export type CitationDto = Schemas["CitationOut"];
export type CitationsInDto = Schemas["CitationsIn"];
export type CitationsOutDto = Schemas["CitationsOut"];
export type SubmitInDto = Schemas["SubmitIn"];
export type ActorInDto = Schemas["ActorIn"];
export type ApproveVersionInDto = Schemas["ApproveVersionIn"];
export type LifecycleDto = Schemas["LifecycleOut"];
export type PublicationDto = Schemas["PublicationOut"];

/** domain_kernel.status.RuleVersionStatus, in the order a version moves through them. */
export const RULE_VERSION_STATUSES = [
  "draft",
  "in_review",
  "approved",
  "published",
  "superseded",
  "withdrawn",
] as const satisfies readonly RuleVersionStatus[];

/** The statuses of a version in force on its dates (`GET /v1/rulebook/rule-versions?as_of=`). */
export const IN_FORCE_STATUSES = [
  "published",
  "superseded",
] as const satisfies readonly RuleVersionStatus[];

/** The seed status until an analyst's approval completes a review round. */
export const NEEDS_REVIEW: SeedStatus = "needs_review";

/** The problem slug the version routes answer for an id the rulebook does not hold. */
export const RULE_VERSION_NOT_FOUND = "rulebook-rule-version-not-found";

/** A rule by its key, with the title of its latest version. */
export interface RuleSummary {
  ruleKey: string;
  ruleId: string;
  regulator: string;
  title: string;
}

/** The instrument a version is taken from, which the analyst checks it against. */
export interface RuleSource {
  instrument: string;
  reference: string;
  note: string;
  url: string;
}

/** The obligation a version creates for a business it applies to. */
export interface ObligationTemplate {
  title: string;
  steps: readonly string[];
  /** Days from the trigger for a one-off duty; null for a recurring one. */
  dueInDays: number | null;
  evidenceType: string | null;
}

/** How the obligation recurs: monthly, quarterly, half_yearly or annual, due on a day. */
export interface Recurrence {
  frequency: string;
  dueDay: number | null;
  /** Months after the period's end; 0 is the month that follows it. */
  dueMonthOffset: number | null;
}

export type SpecValue = string | number | boolean;

/**
 * The applicability condition, read from the kernel's mapping (`specification_to_mapping`):
 * all_of, any_of, not, or a predicate on one attribute (an operator and a value, or free text an
 * analyst or a model has to judge). A node the web app cannot read is kept as `unreadable` with
 * its raw mapping, so a new shape on the service shows up as such instead of as the wrong words.
 */
export type SpecNode =
  | { kind: "all_of"; items: readonly SpecNode[] }
  | { kind: "any_of"; items: readonly SpecNode[] }
  | { kind: "not"; item: SpecNode }
  | {
      kind: "predicate";
      attribute: string;
      /** The kernel's operator (eq, in, gt, contains_any, ...), or null for free text alone. */
      operator: string | null;
      /** The expected value; a list for in, not_in and contains_any. */
      values: readonly SpecValue[];
      /** Whether the value is a list. */
      multi: boolean;
      /** What has to be judged, when the predicate is free text. */
      freeText: string;
    }
  | { kind: "unreadable"; raw: unknown };

export interface RuleVersion {
  ruleVersionId: string;
  ruleId: string;
  ruleKey: string;
  regulator: string;
  level: VersionLevel;
  version: number;
  status: RuleVersionStatus;
  title: string;
  summary: string;
  /** Null when the version states no condition yet (an empty mapping). */
  specification: SpecNode | null;
  obligationTemplate: ObligationTemplate | null;
  recurrence: Recurrence | null;
  /** ISO dates; `effectiveTo` is exclusive and null while open-ended. */
  effectiveFrom: string;
  effectiveTo: string | null;
  source: RuleSource;
  seedStatus: SeedStatus;
  /** True until an analyst's approval completes a review round. */
  needsReview: boolean;
  /** The questions an analyst answers before publication. */
  todo: readonly string[];
  publishedAt: string | null;
  /**
   * The user ids of the approvers of the round the version was published from, as the detail
   * route names them; empty until it is published, and for a version read from a list.
   */
  approvedBy: readonly string[];
  /** Publishing needs two different approvers (ADR-006). */
  highImpact: boolean;
  /**
   * A draft whose rule candidate was rejected: it stays a draft and never moves on (citing,
   * submitting, approving, publishing and approving a relation onto it are refused).
   */
  closed: boolean;
  /** The four open mappings as stored, for the "as stored" view. */
  stored: {
    specification: Record<string, unknown>;
    obligationTemplate: Record<string, unknown>;
    recurrence: Record<string, unknown> | null;
    source: Record<string, unknown>;
  };
}

/** A clause the version cites, with the quote and its one-way verification. */
export interface Citation {
  citationId: string;
  ruleVersionId: string;
  clauseId: string;
  documentId: string;
  clauseRef: string;
  quote: string;
  verified: boolean;
  matchScore: number | null;
  verifiedAt: string | null;
}

/** One citation an analyst asks for: a clause by its id and the words of it the rule rests on. */
export interface CitationInput {
  clauseId: string;
  quote: string;
}

/** What `PUT .../citations` stored: how many are new, how many were there, and every citation. */
export interface CitationReport {
  added: number;
  unchanged: number;
  citations: readonly Citation[];
}

export interface LifecycleEvent {
  eventId: string;
  topic: string;
}

/** A version after a step of the review flow, with the approvers of its current round. */
export interface VersionLifecycle {
  ruleVersionId: string;
  ruleId: string;
  version: number;
  status: RuleVersionStatus;
  seedStatus: SeedStatus;
  highImpact: boolean;
  effectiveFrom: string;
  effectiveTo: string | null;
  /** The start of the current review round. */
  submittedAt: string | null;
  publishedAt: string | null;
  /** The user ids of the round's approvers, in the rulebook's order. */
  approvedBy: readonly string[];
  /** One approver, or two different ones for a high-impact version. */
  requiredApprovals: number;
  /** The events the step wrote to the rulebook's outbox. */
  events: readonly LifecycleEvent[];
}

export interface Replacement {
  ruleVersionId: string;
  relation: string;
  effectiveTo: string | null;
  status: RuleVersionStatus;
  movesTo: RuleVersionStatus;
  /** True until the published version takes effect; the daily sweep moves it. */
  pending: boolean;
}

export interface DeadlineChange {
  ruleVersionId: string;
  periodLabel: string | null;
  newDueOn: string;
  evidenceClauseId: string;
}

/** What publishing did: the lifecycle, the versions it replaces and the due dates it moved. */
export interface Publication extends VersionLifecycle {
  correlationId: string;
  replacements: readonly Replacement[];
  deadlineChanges: readonly DeadlineChange[];
  attributeKeys: readonly string[];
}

/** The steps an analyst takes on a version, one route each. */
export type WorkflowStep = "submit" | "return" | "approve" | "publish" | "withdraw";

// ---- Review tasks (the rulebook's review queue: GET /v1/rulebook/review/tasks*) -----------------

/*
 * A review task asks for one decision on a rule version: approve it, return it for rework, or
 * reject it. A task of kind `seed` reviews a draft the seed calendar wrote; one of kind
 * `candidate` reviews a rule candidate the pipeline extracted, and has no version until its
 * claimant drafts one from the candidate. A task is opened, claimed by the analyst who works on
 * it, and decided once; the first of the two approvals a high-impact version needs leaves it open
 * again for a second, different reviewer. The wire shapes are the rulebook spec's.
 */
export type ReviewTaskKind = Schemas["ReviewTaskKind"];
export type ReviewTaskStatus = Schemas["ReviewTaskStatus"];
export type ReviewDecision = Schemas["ReviewDecision"];
export type RuleRejectReason = Schemas["RuleRejectReason"];
export type CandidateOutcome = Schemas["CandidateOutcome"];
export type RuleCandidateStatus = Schemas["RuleCandidateStatus"];
export type DecisionAction = Schemas["DecisionAction"];

export type ReviewTaskDto = Schemas["ReviewTaskOut"];
export type QueuedTaskDto = Schemas["QueuedTaskOut"];
export type QueuedCandidateDto = Schemas["QueuedCandidateOut"];
export type TaskPageDto = Schemas["Page_QueuedTaskOut_"];
export type ReviewTaskDetailDto = Schemas["ReviewTaskDetailOut"];
export type RuleCandidateDto = Schemas["CandidateOut"];
export type ProposedDraftDto = Schemas["ProposedDraftOut"];
export type TaskDocumentDto = Schemas["TaskDocumentOut"];
export type AuditEntryDto = Schemas["AuditEntryOut"];
export type TaskDecisionDto = Schemas["TaskDecisionOut"];
export type SeedTasksDto = Schemas["SeedTasksOut"];
export type ReviewStatsDto = Schemas["ReviewStatsOut"];
export type ClaimInDto = Schemas["ClaimIn"];
export type DraftFieldsInDto = Schemas["DraftFieldsIn"];
export type DraftEditInDto = Schemas["DraftEditIn"];
export type DraftFromCandidateInDto = Schemas["DraftFromCandidateIn"];
export type DecideInDto = Schemas["DecideIn"];

export const REVIEW_TASK_KINDS = membersOf<ReviewTaskKind>({ seed: true, candidate: true });

export const REVIEW_TASK_STATUSES = membersOf<ReviewTaskStatus>({
  open: true,
  claimed: true,
  decided: true,
});

export const REVIEW_DECISIONS = membersOf<ReviewDecision>({
  approve: true,
  return: true,
  reject: true,
});

export const RULE_REJECT_REASONS = membersOf<RuleRejectReason>({
  not_a_rule: true,
  wrong_extraction: true,
  duplicate: true,
  out_of_scope: true,
  unparseable: true,
});

export const DECISION_ACTIONS = membersOf<DecisionAction>({
  submitted: true,
  returned: true,
  approved: true,
  published: true,
  withdrawn: true,
  superseded: true,
  edited: true,
});

/** The rulebook's limit on a decision's note, a draft's title, its summary and its questions. */
export const REVIEW_NOTE_MAX = 2000;
export const DRAFT_TITLE_MAX = 300;
export const DRAFT_SUMMARY_MAX = 4000;
export const DRAFT_TODO_MAX = 20;
export const DRAFT_QUESTION_MAX = 500;
/** The kernel's frequencies of a recurring duty (domain_kernel.recurrence.Frequency). */
export const FREQUENCIES = ["monthly", "quarterly", "half_yearly", "annual"] as const;

export interface ReviewTask {
  taskId: string;
  /** The version the task reviews; null for a candidate task not drafted yet. */
  ruleVersionId: string | null;
  kind: ReviewTaskKind;
  candidateId: string | null;
  /** Higher comes first within a regulator. */
  priority: number;
  regulator: string;
  status: ReviewTaskStatus;
  openedAt: string;
  claimedBy: string | null;
  claimedAt: string | null;
  decision: ReviewDecision | null;
  decidedBy: string | null;
  decidedAt: string | null;
  /** The decision's note. */
  note: string;
}

/** What the queue shows of a candidate task's candidate. */
export interface QueuedCandidate {
  candidateId: string;
  documentId: string;
  status: RuleCandidateStatus;
  /** extracted, or unparseable: no candidate, so an analyst drafts by hand. */
  outcome: CandidateOutcome;
  confidence: number;
  needsReview: boolean;
  issueCount: number;
  suggestedRuleKey: string | null;
  highImpactSuggested: boolean;
}

/** A row of the queue: the task with its version's rule, number, title and status. */
export interface QueuedTask extends ReviewTask {
  /** The version's rule; before drafting, the key suggested for the candidate. */
  ruleKey: string | null;
  /** Null before drafting. */
  version: number | null;
  /** The version's title, or the candidate's before drafting. */
  title: string;
  versionStatus: RuleVersionStatus | null;
  /** Before drafting, what the candidate suggests. */
  highImpact: boolean;
  /** Distinct approvers of the version's current review round. */
  approvals: number;
  requiredApprovals: number;
  candidate: QueuedCandidate | null;
}

export interface TaskPage {
  tasks: QueuedTask[];
  /** Send as `cursor` for the next page; null on the last page. */
  nextCursor: string | null;
}

/** A document a version cites (or a candidate came from): its clauses are a separate read. */
export interface TaskDocument {
  documentId: string;
  regulator: string;
  docType: string;
  externalRef: string;
  title: string;
  url: string;
  publishedAt: string | null;
}

/** A row of a version's append-only decision audit. */
export interface AuditEntry {
  decisionId: string;
  action: DecisionAction;
  fromStatus: RuleVersionStatus;
  toStatus: RuleVersionStatus;
  actorId: string | null;
  causedByRuleVersionId: string | null;
  note: string;
  decidedAt: string;
}

export interface ExtractionIssue {
  /** The check that failed, such as citation_quote_not_found. */
  code: string;
  detail: string;
  clauseRef: string | null;
}

export interface ProposedCitation {
  clauseRef: string;
  clauseId: string;
  quote: string;
}

/**
 * The draft a candidate proposes, before the analyst's edits, in the stored forms: each field
 * the candidate maps, null for one it does not (`problems` says why), and its quotes.
 */
export interface ProposedDraft {
  title: string | null;
  summary: string | null;
  /** The mapping as proposed; null when a condition is refused. */
  specification: Record<string, unknown> | null;
  obligationTemplate: Record<string, unknown> | null;
  recurrence: Record<string, unknown> | null;
  effectiveFrom: string | null;
  effectiveTo: string | null;
  citations: readonly ProposedCitation[];
  problems: readonly string[];
}

/** A candidate task's rule candidate: the extraction as stored and the draft it proposes. */
export interface RuleCandidate {
  candidateId: string;
  documentId: string;
  document: TaskDocument | null;
  regulator: string;
  model: string;
  promptVersion: string;
  confidence: number;
  /** Quotes the pipeline verified against the clauses. */
  citationCount: number;
  needsReview: boolean;
  outcome: CandidateOutcome;
  status: RuleCandidateStatus;
  rejectReason: RuleRejectReason | null;
  /** The version drafted from it. */
  ruleVersionId: string | null;
  suggestedRuleKey: string | null;
  /** Whether a rule has the suggested key. */
  suggestedRuleKnown: boolean;
  highImpactSuggested: boolean;
  highImpactReasons: readonly string[];
  issues: readonly ExtractionIssue[];
  docType: string | null;
  sourceKey: string | null;
  ontologyVersion: string | null;
  proposed: ProposedDraft;
  createdAt: string;
  decidedBy: string | null;
  decidedAt: string | null;
}

/** A task with everything its workbench shows. */
export interface ReviewTaskDetail {
  task: ReviewTask;
  /** The version the task reviews; null for a candidate task not drafted yet. */
  version: RuleVersion | null;
  /** The predicate tree as the rulebook describes it, two spaces deeper per level. */
  specificationDescribed: readonly string[];
  citations: readonly Citation[];
  /** The documents the citations cite. */
  documents: readonly TaskDocument[];
  sourceUrl: string | null;
  /** Approvers of the version's current round. */
  approvedBy: readonly string[];
  requiredApprovals: number;
  decisions: readonly AuditEntry[];
  /** Every task of the version (of the candidate before drafting), oldest first. */
  tasks: readonly ReviewTask[];
  candidate: RuleCandidate | null;
}

/** What a decision did: the task after it, the version, the next task a return opened. */
export interface TaskDecision {
  task: ReviewTask;
  /** Null for a candidate rejected before drafting. */
  version: VersionLifecycle | null;
  nextTaskId: string | null;
  candidateStatus: RuleCandidateStatus | null;
}

export interface SeedTasksOpened {
  /** Tasks this request opened; 0 when every draft already has one. */
  opened: number;
  taskIds: readonly string[];
}

export interface StatusCounts {
  open: number;
  claimed: number;
  decided: number;
}

export interface ReviewStats {
  byStatus: StatusCounts;
  byRegulator: readonly (StatusCounts & { regulator: string })[];
  decisions: { approved: number; returned: number; rejected: number };
  candidates: {
    decided: number;
    approved: number;
    approvedWithoutEdits: number;
    rejected: number;
    /** The share approved without edits (ADR-006's measure); null while none is decided. */
    acceptanceRate: number | null;
  };
  /** From a task's opening to its decision, over every decided task; null while none is. */
  medianSecondsToDecide: number | null;
  /** The oldest task not decided yet. */
  oldestOpenAt: string | null;
  /** Its age when the stats were read; 0 when none waits. */
  oldestOpenAgeSeconds: number;
}

/**
 * The content of a draft an analyst changes: each field present is sent, one left out keeps its
 * value, and null clears the recurrence or the end date. The three mappings travel in the
 * kernel's forms.
 */
export interface DraftFields {
  title?: string;
  summary?: string;
  specification?: Record<string, unknown>;
  obligationTemplate?: Record<string, unknown>;
  recurrence?: Record<string, unknown> | null;
  effectiveFrom?: string;
  effectiveTo?: string | null;
  todo?: readonly string[];
}

/** An edit of a claimed task's draft: changed fields, citations to add and why. */
export interface DraftEdit {
  fields: DraftFields;
  citations: readonly CitationInput[];
  note: string;
}

/** A version drafted from a candidate task's candidate. */
export interface DraftFromCandidate {
  ruleKey: string;
  /** For a key no rule has: the new rule's regulator and level. */
  newRule: { regulator: string; level: VersionLevel } | null;
  /** Changes to the content the candidate proposes; null keeps it as proposed. */
  edits: DraftFields | null;
  /** The quotes to cite instead of the candidate's; null cites the candidate's. */
  citations: readonly CitationInput[] | null;
  /** Relation candidates of the candidate's document to approve onto the draft. */
  relations: readonly { candidateId: string; targetRuleVersionId: string | null }[];
  note: string;
}

export interface TaskDecisionInput {
  decision: ReviewDecision;
  note: string;
  /** With approve: tag the version high impact before this approval counts. */
  highImpact: boolean;
  /** With reject, for a candidate task: why the candidate is rejected. */
  reason: RuleRejectReason | null;
}
