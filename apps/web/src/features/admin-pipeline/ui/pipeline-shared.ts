/**
 * What the pipeline pages' client panels and their server actions share, in the ui directory so
 * the client components may import it: the field names, the limits the pipeline applies (checked
 * again in the actions and by the pipeline, which owns the rules), and the shapes of an answer.
 */
export const RETRY_FIELDS = {
  stage: "stage",
  docType: "doc_type",
  reason: "reason",
} as const;

export const REQUEUE_FIELDS = { eventId: "event_id", reason: "reason" } as const;

export const RESOLVE_FIELDS = {
  title: "title",
  transcript: "transcript",
  relevance: "relevance",
  docType: "doc_type",
  reason: "reason",
} as const;

export const DISMISS_FIELDS = { reason: "reason" } as const;

/** The fewest characters of a reason, once trimmed: the pipeline's rule for every write. */
export const REASON_MIN_LENGTH = 10;

/** The longest reason the pipeline's audit entry keeps. */
export const REASON_MAX_LENGTH = 2000;

/** The longest transcript title the pipeline takes. */
export const TRANSCRIPT_TITLE_MAX = 500;

/** The stages a retry starts the stored document's ingest again from, in the order shown. */
export const STAGES = ["parse", "classify", "extract"] as const;

export type Stage = (typeof STAGES)[number];

/** The document types, in the order shown. */
export const TYPES = [
  "notification",
  "circular",
  "press_release",
  "act_amendment",
  "statute",
] as const;

/** The types a rule is extracted from: a retry from the extraction takes only these. */
export const EXTRACTED_TYPES: readonly string[] = ["notification", "circular", "act_amendment"];

/** What a write answered: the sentence to announce. */
export interface WriteResult {
  message: string;
}

/**
 * The problem types after which the same request may still go through: the pipeline recorded it
 * (or holds nothing yet) and only Temporal did not answer, so sending it again starts the work.
 */
export const RESENDABLE_PROBLEMS: readonly string[] = [
  "urn:compliancewatch:problem:pipeline-ingest-unavailable",
  // The pipeline did not answer this server in time: it may have done the work, and the same
  // request is answered as the first one was (a retry by its key, a resolution or a requeue as it
  // stands now).
  "urn:compliancewatch:problem:web-network",
];

export function isResendable(problemType: string): boolean {
  return RESENDABLE_PROBLEMS.includes(problemType);
}

/** Whether a write may be offered, and why not (the refusal names the role or the variable). */
export type AccessView = { allowed: true } | { allowed: false; title: string; detail?: string };

export interface EventRow {
  eventId: string;
  topic: string;
  key: string;
  attempts: number;
  lastError: string;
  deadAt: string | null;
  deadAtIso: string | null;
  occurred: string;
  occurredIso: string;
  schemaVersion: string;
  payloadBytes: number;
  /** What the event is about, from its payload, as name and value pairs. */
  summary: readonly (readonly [string, string])[];
}
