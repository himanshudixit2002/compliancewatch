import type { rulebook } from "@compliancewatch/contracts/openapi";

/**
 * The rulebook's changes feed (`GET /v1/changes`): one item per change the rule events announced,
 * newest first. `kind` says what happened to the version: published, superseded, withdrawn, or a
 * due date it moved (deadline_changed). The rest is the version as it stands now: its rule, dates,
 * status and regulator; the seed status (needs_review until an analyst reviews it, the cue for a
 * not-yet-reviewed notice); the approvers of the round it was published from; its verified
 * citations; and the versions it acts on. The feed is the same for every tenant.
 */
type Schemas = rulebook.components["schemas"];

export type RuleChangeDto = Schemas["RuleChangeOut"];
export type RuleChangePageDto = Schemas["Page_RuleChangeOut_"];
export type RuleChangeKind = Schemas["RuleChangeKind"];
export type SeedStatus = Schemas["SeedStatus"];
export type ChangedVersionStatus = Schemas["RuleVersionStatus"];

export const RULE_CHANGE_KINDS: readonly RuleChangeKind[] = [
  "published",
  "superseded",
  "withdrawn",
  "deadline_changed",
];

export interface ChangeCitation {
  clauseId: string;
  documentId: string;
  clauseRef: string;
  quote: string;
}

/** What a deadline change moved: the period (null when the version does not recur). */
export interface DeadlineMove {
  periodLabel: string | null;
  /** A date key; null when the change names none. */
  newDueOn: string | null;
  evidenceClauseId: string | null;
}

export interface DeadlineExtension {
  ruleVersionId: string;
  periodLabel: string | null;
  newDueOn: string | null;
}

/** The versions a version acts on when it is published. */
export interface ChangeRelations {
  supersedes: readonly string[];
  corrects: readonly string[];
  withdraws: readonly string[];
  extendsDeadline: readonly DeadlineExtension[];
}

export interface RuleChange {
  id: string;
  kind: RuleChangeKind;
  /** When the change was published. */
  changedAt: string;
  ruleVersionId: string;
  ruleKey: string;
  title: string;
  summary: string;
  version: number;
  regulator: string;
  /** entity, registration or location: the level of the businesses the rule is decided for. */
  level: string;
  status: ChangedVersionStatus;
  /** Date keys; the end is exclusive and null while open-ended. */
  effectiveFrom: string;
  effectiveTo: string | null;
  seedStatus: SeedStatus;
  approvedBy: readonly string[];
  publishedAt: string | null;
  citations: readonly ChangeCitation[];
  causedByRuleVersionId: string | null;
  deadline: DeadlineMove | null;
  relations: ChangeRelations;
}

export interface RuleChangePage {
  items: readonly RuleChange[];
  nextCursor: string | null;
}
