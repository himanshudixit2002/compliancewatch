import type { EntityRejectReason, MentionDecision } from "@/entities/rulebook/types";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * What the decision panel and its server action share, in the ui directory so the client panel
 * may import it: the field names (the rulebook's body fields, so a 422's `errors[].loc` lands on
 * the right field), the limits the rulebook states (checked again in the action), the form's id
 * and the shape of an answer.
 */
export const DECISION_FIELDS = {
  decision: "decision",
  entityId: "entity_id",
  rejectReason: "reject_reason",
  reviewIds: "review_ids",
  note: "note",
} as const;

/** The rulebook keeps a note of up to 2000 characters with each decided mention. */
export const NOTE_MAX_LENGTH = 2000;

/** One decision names at most 200 mentions. */
export const REVIEW_IDS_MAX = 200;

/**
 * The rulebook lists at most 200 open mentions of a group (its page limit). A list that long is
 * the first 200 of a group that may hold more, and a decision over the whole group covers every
 * open mention, listed or not, so the page never states a count it does not know.
 */
export const GROUP_ITEMS_MAX = 200;

/** Whether the list is the rulebook's first 200, so the group may hold more. */
export function isCapped(listed: number): boolean {
  return listed >= GROUP_ITEMS_MAX;
}

/** How many open mentions the group holds, as far as the list tells: "3", or "200 or more ...". */
export function openCountText(listed: number): string {
  return isCapped(listed) ? t("entityReview.openCapped", { max: GROUP_ITEMS_MAX }) : String(listed);
}

/** Whether the page may offer decisions: the role, the flag and the review token allow it. */
export type AccessView = { allowed: true } | { allowed: false; title: string; detail?: string };

/** One open mention as the items table shows it. */
export interface ItemRow {
  reviewId: string;
  text: string;
  reasonLabel: string;
  documentId: string;
  /** The document viewer with this mention marked. */
  documentHref: string;
}

/** What a decision recorded, as the panel announces it. */
export interface DecisionResult {
  message: string;
  statusLabel: string;
  resolutionLabel: string | null;
  entityId: string | null;
  /** The canonical entity the decision made or extended, once there is one. */
  entityHref: string | null;
  itemsClosed: number;
  relationTargetsUpdated: number;
}

const DECISIONS: Readonly<Record<MentionDecision, { label: MessageKey; help: MessageKey }>> = {
  create_entity: {
    label: "entityReview.decision.createEntity",
    help: "entityReview.decision.createEntityHelp",
  },
  add_alias: {
    label: "entityReview.decision.addAlias",
    help: "entityReview.decision.addAliasHelp",
  },
  reject: { label: "entityReview.decision.reject", help: "entityReview.decision.rejectHelp" },
};

export function decisionLabel(decision: MentionDecision): string {
  return t(DECISIONS[decision].label);
}

export function decisionHelp(decision: MentionDecision): string {
  return t(DECISIONS[decision].help);
}

const REJECT_REASONS: Readonly<Record<EntityRejectReason, MessageKey>> = {
  not_an_entity: "entityReview.rejectReason.notAnEntity",
  wrong_type: "entityReview.rejectReason.wrongType",
  text_artifact: "entityReview.rejectReason.textArtifact",
  out_of_scope: "entityReview.rejectReason.outOfScope",
};

export function rejectReasonLabel(reason: EntityRejectReason): string {
  return t(REJECT_REASONS[reason]);
}
