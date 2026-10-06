import type {
  DecisionDto,
  DryRunOutDto,
  FanOutHoldDto,
  FanOutRunDto,
  ReviewItemDto,
} from "@/entities/applicability/types";
import type { BulkNotificationOutDto } from "@/entities/notification/types";
import { DECISION_ID, REGISTRATION_ID, RULE_VERSION_ID, decisionDto } from "./obligation-fixture";

/**
 * The applicability engine's admin bodies for unit tests (fan-out runs, the global hold, review
 * items, dry runs) and the notification service's bulk answer: fixed synthetic ids, "Example ..."
 * text, dates in the year 2000. The e2e suite reads the real services.
 */
export const RUN_VERSION_ID = "00000000-0000-4000-8000-00000000f0a1";
export const OLDER_VERSION_ID = "00000000-0000-4000-8000-00000000f0a0";
export const TRIGGER_EVENT_ID = "00000000-0000-4000-8000-00000000f0e1";
export const REVIEW_ITEM_ID = "00000000-0000-4000-8000-00000000f0b1";
export const REVIEWER_ID = "00000000-0000-4000-8000-00000000f0c1";
export const REVIEWED_TENANT_ID = "00000000-0000-4000-8000-00000000f0d1";
export const ADMIN_USER_ID = "00000000-0000-4000-8000-00000000f0c2";

export function fanOutRunDto(overrides: Partial<FanOutRunDto> = {}): FanOutRunDto {
  return {
    rule_version_id: RUN_VERSION_ID,
    rule_key: "example_rule",
    level: "registration",
    status: "running",
    trigger_event_id: TRIGGER_EVENT_ID,
    supersedes: [],
    businesses_total: 2000,
    evaluated: 1000,
    applies: 400,
    flips_compared: 0,
    flips: 0,
    flip_rate: null,
    started_at: "2000-01-05T04:30:00Z",
    updated_at: "2000-01-05T04:35:00Z",
    finished_at: null,
    status_reason: "",
    status_by: "system:applicability-engine",
    last_error: "",
    ...overrides,
  };
}

export function holdDto(overrides: Partial<FanOutHoldDto> = {}): FanOutHoldDto {
  return { held: false, reason: null, set_by: null, set_at: null, ...overrides };
}

export function heldDto(reason = "Example deploy of the rulebook in progress"): FanOutHoldDto {
  return {
    held: true,
    reason,
    set_by: "system:applicability-engine",
    set_at: "2000-01-06T04:30:00Z",
  };
}

/** An unsure decision with a free-text predicate nobody judged. */
export function unsureDecisionDto(overrides: Partial<DecisionDto> = {}): DecisionDto {
  return decisionDto({
    result: "unsure",
    confidence: 0.5,
    needs_review: true,
    evaluated: [
      {
        attribute: "example_kind",
        kind: "structured",
        description: "Example kind is second",
        predicate: { attribute: "example_kind", operator: "eq", value: "second" },
        outcome: "applies",
        confidence: 1,
        reason: "Example kind is second on this node",
        needs_review: false,
      },
      {
        attribute: "example_question",
        kind: "free_text",
        description: "Example condition a person judges",
        predicate: { attribute: "example_question", free_text: "Example condition." },
        outcome: "unsure",
        confidence: 0,
        reason: "Example free text nobody judged yet",
        needs_review: true,
      },
    ],
    ...overrides,
  });
}

export function reviewItemDto(overrides: Partial<ReviewItemDto> = {}): ReviewItemDto {
  return {
    item_id: REVIEW_ITEM_ID,
    business_id: REGISTRATION_ID,
    rule_version_id: RULE_VERSION_ID,
    reason: "free_text",
    status: "open",
    opened_at: "2000-01-04T04:30:00Z",
    decision: unsureDecisionDto(),
    resolution: null,
    resolved_by: null,
    resolved_at: null,
    note: "",
    resolution_decision_id: null,
    ...overrides,
  };
}

export function resolvedItemDto(overrides: Partial<ReviewItemDto> = {}): ReviewItemDto {
  return reviewItemDto({
    status: "resolved",
    resolution: "applies",
    resolved_by: REVIEWER_ID,
    resolved_at: "2000-01-06T05:00:00Z",
    note: "Example note on why it applies",
    resolution_decision_id: DECISION_ID,
    ...overrides,
  });
}

export function dryRunOutDto(overrides: Partial<DryRunOutDto> = {}): DryRunOutDto {
  return {
    rule_version_id: RUN_VERSION_ID,
    rule_key: "example_rule",
    status: "draft",
    level: "registration",
    tenant_id: null,
    as_of_fy: "1999-00",
    businesses_total: 3,
    evaluated: 3,
    skipped: 0,
    counts: { applies: 1, not_applicable: 1, unsure: 1 },
    needs_review: 1,
    by_attribute: [
      { attribute: "example_kind", applies: 1, not_applicable: 1, unsure: 0 },
      { attribute: "example_question", applies: 0, not_applicable: 0, unsure: 1 },
    ],
    samples: [
      {
        tenant_id: REVIEWED_TENANT_ID,
        business_id: REGISTRATION_ID,
        profile_version: 2,
        result: "applies",
        confidence: 1,
        needs_review: false,
        deciding: ["example_kind"],
        evaluated: decisionDto().evaluated,
      },
    ],
    max_businesses: 2000,
    ran_at: "2000-01-07T04:30:00Z",
    ...overrides,
  };
}

export function bulkOutDto(
  overrides: Partial<BulkNotificationOutDto> = {},
): BulkNotificationOutDto {
  return {
    rule_version_id: RUN_VERSION_ID,
    kind: "change_card",
    queued: 1,
    skipped_duplicate: 0,
    skipped_no_recipient: 0,
    skipped_not_affected: 0,
    notifications_queued: 2,
    businesses: [
      {
        business_id: REGISTRATION_ID,
        outcome: "queued",
        obligation_id: "00000000-0000-4000-8000-00000000f0f1",
        queued: 2,
        duplicates: 0,
        unreachable: 0,
      },
    ],
    ...overrides,
  };
}
