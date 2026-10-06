/**
 * What the fan-out pages' client panels and their server actions share, in the ui directory so
 * the client components may import it: the field names, the limits the engine applies to a
 * reason (checked again in the action; the engine owns the rules), and the shapes of an answer.
 */
export const CONTROL_FIELDS = {
  /** pause, resume or cancel. */
  control: "control",
  /** "on" sets the hold, "off" releases it. */
  hold: "hold",
  reason: "reason",
} as const;

/** The fewest characters of a reason, once trimmed: the engine's and the rulebook's rule. */
export const REASON_MIN_LENGTH = 10;

/** The longest reason the audit log keeps. */
export const REASON_MAX_LENGTH = 2000;

/** What a control answered: the sentence to announce. */
export interface ControlResult {
  message: string;
}

/** Whether a write may be offered, and why not (the refusal names the flag or the variable). */
export type AccessView = { allowed: true } | { allowed: false; title: string; detail?: string };

/** A read that failed, with the correlation id to quote. */
export interface ReadFailure {
  message: string;
  correlationId: string | null;
}

/** Whether the rollback is offered, and if not, why: the shape the page's query builds. */
export type RollbackState =
  | { state: "offered"; access: AccessView }
  | { state: "not_admin" }
  | { state: "not_published"; statusLabel: string }
  | { state: "unknown_version" };

/** A control an admin sends to one run; the hold is the pages' other control. */
export type FanOutControl = "pause" | "resume" | "cancel";

/** The global hold as the pages say it. */
export interface HoldView {
  held: boolean;
  reason: string | null;
  by: string | null;
  since: string | null;
}
