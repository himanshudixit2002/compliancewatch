import type { obligation } from "@compliancewatch/contracts/openapi";

/**
 * A business's obligations as the obligation service returns them: one duty of one profile node
 * (a GSTIN's returns are kept for its registration), for one period when its rule recurs, with
 * what the service keeps of the rule version it comes from (the title, whether the seed rule is
 * reviewed, the approvers of the round it was published from) and the verified quotes of the
 * clause it cites. The detail adds the history and the comments.
 *
 * Instants are ISO strings in UTC; `dueAt` is the end of the due day in India, so the due day is
 * read in IST. The domain names are camel case; the mappers own the translation from the wire.
 */
type Schemas = obligation.components["schemas"];

export type ObligationDto = Schemas["ObligationOut"];
export type ListedObligationDto = Schemas["BusinessObligationOut"];
export type ObligationPageDto = Schemas["Page_BusinessObligationOut_"];
export type ObligationDetailDto = Schemas["ObligationDetailOut"];
export type RuleVersionFactsDto = Schemas["RuleVersionFactsOut"];
export type ObligationCitationDto = Schemas["CitationOut"];
export type ObligationChangeDto = Schemas["ChangeOut"];
export type ObligationCommentDto = Schemas["CommentOut"];
export type StatusInDto = Schemas["StatusIn"];

export type ObligationStatus = Schemas["ObligationStatus"];
export type ClosureReason = Schemas["ClosureReason"];
export type ObligationChangeKind = Schemas["ChangeKind"];
export type StatusAction = Schemas["StatusAction"];
export type RuleVersionStatus = Schemas["RuleVersionStatus"];

export const OBLIGATION_STATUSES: readonly ObligationStatus[] = [
  "open",
  "in_progress",
  "done",
  "waived",
  "closed_not_applicable",
];

export const STATUS_ACTIONS: readonly StatusAction[] = ["start", "complete", "waive"];

/** The fewest characters the service takes as a waiver's reason (MIN_WAIVER_CHARS). */
export const MIN_WAIVER_REASON = 10;

/** The longest comment the service keeps (MAX_COMMENT_CHARS). */
export const MAX_COMMENT_LENGTH = 2000;

/** The longest note a status change keeps, a waiver's reason included (MAX_NOTE_CHARS). */
export const MAX_REASON_LENGTH = 2000;

/** What the obligation service keeps of the rule version an obligation comes from. */
export interface RuleVersionFacts {
  ruleVersionId: string;
  ruleKey: string;
  title: string;
  status: RuleVersionStatus;
  /** Date keys; the end is exclusive and null while open-ended. */
  effectiveFrom: string;
  effectiveTo: string | null;
  /** "reviewed" once an analyst checked the seed rule against its source; else needs_review. */
  seedStatus: string;
  reviewed: boolean;
  /** The approvers of the round it was published from (user ids). */
  approvedBy: readonly string[];
  publishedAt: string | null;
}

/** A verified quote of the clause an obligation comes from. */
export interface ObligationCitation {
  citationId: string;
  clauseId: string;
  documentId: string;
  /** The clause's reference in its document, such as en.p3. */
  clauseRef: string;
  quote: string;
  matchScore: number | null;
  verifiedAt: string | null;
}

/** One duty of a profile node, for one period when its rule recurs. */
export interface Obligation {
  id: string;
  /** The profile node it is kept for (an entity, a registration or a location). */
  businessId: string;
  ruleVersionId: string;
  decisionId: string;
  title: string;
  /** What to do, in order. */
  steps: readonly string[];
  /** What proves it was met, as a code such as "filing_acknowledgement"; empty when unnamed. */
  evidenceType: string;
  /** The period's label ("2026-09"); null for a duty that does not recur. */
  periodLabel: string | null;
  /** Date keys; the period is half-open, so the end is the day after its last day. */
  periodStart: string | null;
  periodEnd: string | null;
  /** The end of the due day in India; null when the rule sets no due date. */
  dueAt: string | null;
  status: ObligationStatus;
  closedAt: string | null;
  closedReason: ClosureReason | null;
  /** The profile version of the decision that made it; null for one made before it was kept. */
  profileVersion: number | null;
  /** The user of the tenant it is given to; null for nobody. */
  assigneeId: string | null;
}

/** An obligation of a node's list: with its rule's facts (null before the service kept them). */
export interface ListedObligation extends Obligation {
  ruleVersion: RuleVersionFacts | null;
  citations: readonly ObligationCitation[];
}

export interface ObligationPage {
  items: readonly ListedObligation[];
  /** Send as the cursor for the next page; null on the last page. */
  nextCursor: string | null;
}

/** One change of an obligation, oldest first in its history. */
export interface ObligationChange {
  id: string;
  kind: ObligationChangeKind;
  occurredAt: string;
  statusAfter: ObligationStatus;
  /** The reschedule or closure reason; empty for the other kinds. */
  reason: string;
  /** What the person said, such as a waiver's reason; empty when nothing was said. */
  note: string;
  previousDueAt: string | null;
  newDueAt: string | null;
  previousAssigneeId: string | null;
  newAssigneeId: string | null;
  causedByRuleVersionId: string | null;
  /** The user who made the change; null when the system did or no token named the caller. */
  actor: string | null;
}

export interface ObligationComment {
  id: string;
  obligationId: string;
  /** The user who wrote it; null when no token named the caller. */
  authorId: string | null;
  /** The author as the audit log labels them (roles, or system:obligation), never a name. */
  authorLabel: string;
  body: string;
  createdAt: string;
}

/** One obligation with what its page shows. */
export interface ObligationDetail extends ListedObligation {
  history: readonly ObligationChange[];
  comments: readonly ObligationComment[];
}

/** A status change as the page asks for it; a waiver carries its reason. */
export interface StatusChange {
  action: StatusAction;
  reason: string;
}
