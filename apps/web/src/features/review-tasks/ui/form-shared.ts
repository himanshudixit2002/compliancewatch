import type { FREQUENCIES, VersionLevel } from "@/entities/rule-version/types";
import type { EditorOntology } from "./predicate-tree";

/**
 * What the workbench's client forms and their server actions share, in the ui directory so the
 * client components may import it: the field names (the rulebook's body fields, so a 422's
 * `errors[].loc` lands on its field), the limits the forms check again in the actions, and the
 * plain shapes the pages hand the forms.
 *
 * A draft's content is edited field by field. Each field is posted with the value it was rendered
 * with (`base:<name>`), and only a field whose value changed is sent: an edit names what it
 * changes, the audit row says so, and a field left alone is never overwritten.
 */
export const CONTENT_FIELDS = {
  title: "title",
  summary: "summary",
  effectiveFrom: "effective_from",
  effectiveTo: "effective_to",
  frequency: "recurrence.frequency",
  dueDay: "recurrence.due_day",
  dueMonthOffset: "recurrence.due_month_offset",
  templateTitle: "obligation_template.title",
  templateSteps: "obligation_template.steps",
  templateDueInDays: "obligation_template.due_in_days",
  templateEvidence: "obligation_template.evidence_type",
  todo: "todo",
  specification: "specification",
} as const;

export type ContentField = keyof typeof CONTENT_FIELDS;

/** The prefix of the value a field was rendered with. */
export const BASE_PREFIX = "base:";

/** The draft-from-candidate form sends its content changes under `edits`. */
export const EDITS_PREFIX = "edits.";

export const NOTE_FIELD = "note";

export function citationField(index: number, part: "clause_id" | "quote"): string {
  return `citations.${index}.${part}`;
}

export const DRAFT_FIELDS = {
  ruleKey: "rule_key",
  newRule: "new_rule",
  regulator: "new_rule.regulator",
  level: "new_rule.level",
  citationsMode: "citations_mode",
} as const;

export function relationField(
  index: number,
  part: "candidate_id" | "target_rule_version_id",
): string {
  return `relation_candidates.${index}.${part}`;
}

export const DECIDE_FIELDS = {
  decision: "decision",
  note: "note",
  highImpact: "high_impact",
  reason: "reason",
} as const;

/** The task a queue row's claim names. */
export const CLAIM_FIELD = "task_id";

/** The rulebook's limits (rulebook.domain.drafting, review_tasks and intake). */
export const LIMITS = {
  note: 2000,
  title: 300,
  summary: 4000,
  todo: 20,
  question: 500,
  ruleKey: 80,
  regulator: 40,
  citations: 50,
  quote: 400,
  relations: 50,
  dueDay: 31,
  dueMonthOffset: 24,
} as const;

/** domain_kernel's rule key pattern, as the draft route checks it. */
export const RULE_KEY = /^[a-z][a-z0-9_]*$/;

export type Frequency = (typeof FREQUENCIES)[number];

/** Where a new rule applies: the levels of the business hierarchy (ADR-016). */
export const LEVELS: readonly VersionLevel[] = ["entity", "registration", "location"];

/** A draft's content as the form's inputs hold it: text, a line per step or question. */
export interface ContentValues {
  title: string;
  summary: string;
  effectiveFrom: string;
  /** Empty for an open-ended version. */
  effectiveTo: string;
  /** Empty for a duty that does not recur. */
  frequency: Frequency | "";
  dueDay: string;
  dueMonthOffset: string;
  templateTitle: string;
  /** One step per line. */
  templateSteps: string;
  /** Empty for a recurring duty, which takes its due date from the recurrence. */
  templateDueInDays: string;
  templateEvidence: string;
  /** One question per line. */
  todo: string;
  /** The kernel's mapping of the condition, as stored; null when there is none. */
  specification: unknown;
}

/** A clause a citation may name: a clause of a cited document, or of the candidate's. */
export interface ClauseOption {
  value: string;
  /** "en.p3: Example clause text that ..." */
  label: string;
  /** The clause's whole text, which the quote must hold word for word. */
  text: string;
}

/** An open relation candidate of the candidate's document, which a draft may take on. */
export interface RelationChoice {
  candidateId: string;
  /** "Extends deadline: Form EX-1". */
  label: string;
  evidenceQuote: string;
  /** The kind needs the version it points at (supersedes, extends a deadline, ...). */
  needsTarget: boolean;
  targetOptions: readonly { value: string; label: string }[];
}

/** Whether the page may send decisions: the role, the flag and the review token allow it. */
export type AccessView = { allowed: true } | { allowed: false; title: string; detail?: string };

/** The ontology the predicate editor offers attributes and words values from. */
export type { EditorOntology };

/** What a write answered, as a panel announces it. */
export interface WriteResult {
  /**
   * "done" for the rulebook's answer to this request; "already" when the request found it done
   * (a task decided before the decision arrived), shown as information.
   */
  kind: "done" | "already";
  message: string;
  /** Further lines: the version's status, the candidate's, the next task. */
  details: readonly string[];
  /** The next task a return opened, or the version's page to publish from. */
  links: readonly { href: string; label: string }[];
}

/** Someone the rulebook names by user id; `you` for the signed-in analyst. */
export interface PersonRef {
  userId: string;
  you: boolean;
}

/** Who holds a task, as the claim panel says it. */
export type ClaimView =
  | { state: "open"; canClaim: boolean }
  | { state: "mine"; at: string | null }
  | { state: "other"; by: PersonRef; at: string | null }
  | { state: "decided" };

/** The edit form of a claimed task's draft. */
export interface EditForm {
  initial: ContentValues;
  clauseOptions: ClauseOption[];
  /** Changes when the draft does, so the form starts again from the stored content. */
  revision: string;
}

/** The form that drafts a version from a candidate task's candidate. */
export interface DraftForm {
  initial: ContentValues;
  ruleKey: string;
  /** A rule has the suggested key: the draft becomes its next version. */
  suggestedKnown: boolean;
  regulator: string;
  ruleKeys: string[];
  relations: RelationChoice[];
  relationsError: {
    message: string;
    requestId: string;
    problem?: { detail?: string | null };
  } | null;
  clauseOptions: ClauseOption[];
  /** The candidate's quotes, cited unless the analyst cites others. */
  proposedCitations: readonly { clauseRef: string; quote: string }[];
  revision: string;
}

/** What the decision panel offers. */
export interface DecideView {
  candidateTask: boolean;
  drafted: boolean;
  canApprove: boolean;
  /** Why approving is not offered, when it is not. */
  approveBlocked: string | null;
  canReturn: boolean;
  canReject: boolean;
  /** The version is tagged high impact already; the tag stays once set. */
  highImpact: boolean;
}

/** The approvals of the version's current round. */
export interface ApprovalsView {
  count: number;
  required: number;
  approvers: PersonRef[];
  /** One approval of two is in: a second, different reviewer completes the round. */
  waitingForAnother: boolean;
}
