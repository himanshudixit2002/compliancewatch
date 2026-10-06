import type { CandidateRejectReason } from "@/entities/rulebook/types";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * What the candidate's decision panel and its server actions share, in the ui directory so the
 * client panel may import it: the field names (the rulebook's body fields, so a 422's
 * `errors[].loc` lands on its field), the note's limit (checked again in the actions), the
 * version choices, what the page may offer and the shape of an answer.
 */
export const APPROVE_FIELDS = {
  fromRuleVersionId: "from_rule_version_id",
  targetRuleVersionId: "target_rule_version_id",
  note: "note",
} as const;

export const REJECT_FIELDS = { reason: "reason", note: "note" } as const;

/** The rulebook keeps a note of up to 2000 characters with the decision. */
export const NOTE_MAX_LENGTH = 2000;

/** A rule version the approve form offers. */
export interface VersionOption {
  value: string;
  label: string;
}

/** Whether the page may offer decisions: the role, the flag and the review token allow it. */
export type AccessView = { allowed: true } | { allowed: false; title: string; detail?: string };

/** What a decision answered, as the panel announces it. */
export interface CandidateDecisionResult {
  message: string;
  /** The rule relation an approval wrote. */
  ruleRelationId: string | null;
  /** The relations graph around the version the relation starts from. */
  graphHref: string | null;
}

const REJECT_REASONS: Readonly<Record<CandidateRejectReason, MessageKey>> = {
  wrong_kind: "relationReview.rejectReason.wrongKind",
  wrong_target: "relationReview.rejectReason.wrongTarget",
  not_in_text: "relationReview.rejectReason.notInText",
  duplicate: "relationReview.rejectReason.duplicate",
  out_of_scope: "relationReview.rejectReason.outOfScope",
};

export function candidateRejectReasonLabel(reason: CandidateRejectReason): string {
  return t(REJECT_REASONS[reason]);
}
