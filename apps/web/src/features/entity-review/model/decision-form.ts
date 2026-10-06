import type { EntityRejectReason, MentionDecision } from "@/entities/rulebook/types";
import { ENTITY_REJECT_REASONS, MENTION_DECISIONS } from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";
import { isHexUuid } from "@/shared/lib/identifiers";
import { DECISION_FIELDS, NOTE_MAX_LENGTH, REVIEW_IDS_MAX } from "../ui/decision-shared";

/**
 * The decision form's shape, checked before the rulebook is asked: one of the three decisions,
 * the entity's id for add_alias, a reason for reject, a note of at most 2000 characters, and at
 * most 200 mention ids (none means every open mention of the group). The rulebook owns the rest.
 * Errors are keyed by the rulebook's body fields, as a 422 from it would be.
 */
function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function isDecision(value: string): value is MentionDecision {
  return (MENTION_DECISIONS as readonly string[]).includes(value);
}

function isRejectReason(value: string): value is EntityRejectReason {
  return (ENTITY_REJECT_REASONS as readonly string[]).includes(value);
}

export type ParsedDecision =
  | {
      ok: true;
      decision: MentionDecision;
      entityId?: string;
      rejectReason?: EntityRejectReason;
      reviewIds?: string[];
      note: string;
    }
  | { ok: false; errors: Record<string, string[]> };

/**
 * `nameable` is canName for the group: a group whose name cannot name an entity is decided by
 * naming its mentions, and cannot make an entity.
 */
export function parseDecision(formData: FormData, nameable = true): ParsedDecision {
  const errors: Record<string, string[]> = {};
  const decision = text(formData, DECISION_FIELDS.decision);
  const entityId = text(formData, DECISION_FIELDS.entityId).trim().toLowerCase();
  const rejectReason = text(formData, DECISION_FIELDS.rejectReason);
  const note = text(formData, DECISION_FIELDS.note).trim();
  const reviewIds = [
    ...new Set(
      formData
        .getAll(DECISION_FIELDS.reviewIds)
        .filter((value): value is string => typeof value === "string")
        .map((value) => value.trim().toLowerCase())
        .filter((value) => value !== ""),
    ),
  ];
  if (!isDecision(decision)) errors[DECISION_FIELDS.decision] = [t("entityReview.error.decision")];
  else if (decision === "create_entity" && !nameable) {
    errors[DECISION_FIELDS.decision] = [t("entityReview.error.notNameable")];
  }
  if (decision === "add_alias" && !isHexUuid(entityId)) {
    errors[DECISION_FIELDS.entityId] = [t("entityReview.error.entityId")];
  }
  if (decision === "reject" && !isRejectReason(rejectReason)) {
    errors[DECISION_FIELDS.rejectReason] = [t("entityReview.error.rejectReason")];
  }
  if (note.length > NOTE_MAX_LENGTH) {
    errors[DECISION_FIELDS.note] = [t("entityReview.error.noteTooLong", { max: NOTE_MAX_LENGTH })];
  }
  if (reviewIds.length > REVIEW_IDS_MAX || reviewIds.some((id) => !isHexUuid(id))) {
    errors[DECISION_FIELDS.reviewIds] = [
      t("entityReview.error.reviewIds", { max: REVIEW_IDS_MAX }),
    ];
  } else if (reviewIds.length === 0 && !nameable) {
    errors[DECISION_FIELDS.reviewIds] = [t("entityReview.error.includeMentions")];
  }
  if (Object.keys(errors).length > 0 || !isDecision(decision)) return { ok: false, errors };
  return {
    ok: true,
    decision,
    ...(decision === "add_alias" ? { entityId } : {}),
    ...(decision === "reject" && isRejectReason(rejectReason) ? { rejectReason } : {}),
    ...(reviewIds.length === 0 ? {} : { reviewIds }),
    note,
  };
}
