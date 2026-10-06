/**
 * What the obligation page's forms and their server actions share, in the ui directory so the
 * client forms may import it: the field names, the shape of an answer, and the limits the service
 * applies (checked again in the action; the service owns the rules).
 */
export const TRACKING_FIELDS = {
  businessId: "business_id",
  obligationId: "obligation_id",
  action: "action",
  reason: "reason",
  assignee: "assignee_id",
  /** Which assignee a button chose: "me" (the signed-in user) or "nobody"; else the field's. */
  assignTo: "assign_to",
  body: "body",
} as const;

export const ASSIGN_TO_ME = "me";
export const ASSIGN_TO_NOBODY = "nobody";

/** The fewest characters of a waiver's reason, as the service counts them once trimmed. */
export const WAIVER_MIN_LENGTH = 10;

/** The longest comment, and the longest reason, the service keeps. */
export const TEXT_MAX_LENGTH = 2000;

/** What a tracking write answered: the sentence to announce, and whether it was a replay. */
export interface TrackingResult {
  message: string;
  /** True when the service answered with the first answer to the same request (same key). */
  replayed: boolean;
}

/** The first obligation of a business, as the onboarding summary's poll learns it. */
export type FirstObligationState =
  | { status: "found"; title: string; due: string; dueNote: string | null; href: string }
  | { status: "none" }
  | { status: "error"; message: string; correlationId: string | null };
