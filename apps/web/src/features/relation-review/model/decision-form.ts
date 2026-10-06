import {
  CANDIDATE_REJECT_REASONS,
  type CandidateApproval,
  type CandidateRejectReason,
  type CandidateRejection,
} from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";
import { isHexUuid } from "@/shared/lib/identifiers";
import { APPROVE_FIELDS, NOTE_MAX_LENGTH, REJECT_FIELDS } from "../ui/decision-shared";

/**
 * The two decision forms' shapes, checked before the rulebook is asked. Approving takes the
 * version the relation starts from, the affected version where the candidate needs one (see
 * needsTargetVersion; the rulebook answers 422 rulebook-target-version-required otherwise), and a
 * note; rejecting takes one of the rulebook's reasons and a note. Errors are keyed by the
 * rulebook's body fields, as a 422 from it would be. The rulebook owns everything else.
 */
function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function noteOf(formData: FormData, errors: Record<string, string[]>): string {
  const note = text(formData, APPROVE_FIELDS.note).trim();
  if (note.length > NOTE_MAX_LENGTH) {
    errors[APPROVE_FIELDS.note] = [t("relationReview.error.noteTooLong", { max: NOTE_MAX_LENGTH })];
  }
  return note;
}

export type ParsedApproval =
  { ok: true; approval: CandidateApproval } | { ok: false; errors: Record<string, string[]> };

export function parseApproval(formData: FormData, needsTarget: boolean): ParsedApproval {
  const errors: Record<string, string[]> = {};
  const from = text(formData, APPROVE_FIELDS.fromRuleVersionId).trim().toLowerCase();
  const target = text(formData, APPROVE_FIELDS.targetRuleVersionId).trim().toLowerCase();
  const note = noteOf(formData, errors);
  if (!isHexUuid(from)) {
    errors[APPROVE_FIELDS.fromRuleVersionId] = [t("relationReview.error.fromVersion")];
  }
  if (target === "" && needsTarget) {
    errors[APPROVE_FIELDS.targetRuleVersionId] = [t("relationReview.error.targetRequired")];
  } else if (target !== "" && !isHexUuid(target)) {
    errors[APPROVE_FIELDS.targetRuleVersionId] = [t("relationReview.error.targetVersion")];
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    approval: {
      fromRuleVersionId: from,
      ...(target === "" ? {} : { targetRuleVersionId: target }),
      note,
    },
  };
}

function isRejectReason(value: string): value is CandidateRejectReason {
  return (CANDIDATE_REJECT_REASONS as readonly string[]).includes(value);
}

export type ParsedRejection =
  { ok: true; rejection: CandidateRejection } | { ok: false; errors: Record<string, string[]> };

export function parseRejection(formData: FormData): ParsedRejection {
  const errors: Record<string, string[]> = {};
  const reason = text(formData, REJECT_FIELDS.reason);
  const note = noteOf(formData, errors);
  if (!isRejectReason(reason)) errors[REJECT_FIELDS.reason] = [t("relationReview.error.reason")];
  if (Object.keys(errors).length > 0 || !isRejectReason(reason)) return { ok: false, errors };
  return { ok: true, rejection: { reason, note } };
}
