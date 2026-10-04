import type { rulebook } from "@compliancewatch/contracts/openapi";

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
  /** Publishing needs two different approvers (ADR-006). */
  highImpact: boolean;
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
