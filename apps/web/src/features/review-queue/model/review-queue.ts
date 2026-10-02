import type { SelectOption, Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/** Where an item stands in the review queue. */
export type ReviewStatus = "pending" | "approved" | "rejected";

/** What kind of record is waiting for a reviewer. */
export type ReviewItemType =
  "attribute_change" | "obligation_review" | "evidence_review" | "consent_change";

export type ReviewPriority = "high" | "medium" | "low";

export const REVIEW_STATUSES: readonly ReviewStatus[] = ["pending", "approved", "rejected"];

export const REVIEW_ITEM_TYPES: readonly ReviewItemType[] = [
  "attribute_change",
  "obligation_review",
  "evidence_review",
  "consent_change",
];

/** One record waiting for, or past, a reviewer's decision. */
export interface ReviewItem {
  id: string;
  type: ReviewItemType;
  title: string;
  description: string;
  status: ReviewStatus;
  priority: ReviewPriority;
  submittedBy: string;
  /** The instant it entered the queue. */
  submittedAt: string;
  businessName: string;
}

/** The figures in the summary row. */
export interface ReviewCounts {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
}

const STATUS_LABEL: Readonly<Record<ReviewStatus, MessageKey>> = {
  pending: "reviewQueue.status.pending",
  approved: "reviewQueue.status.approved",
  rejected: "reviewQueue.status.rejected",
};

const STATUS_TONE: Readonly<Record<ReviewStatus, Tone>> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
};

const TYPE_LABEL: Readonly<Record<ReviewItemType, MessageKey>> = {
  attribute_change: "reviewQueue.type.attributeChange",
  obligation_review: "reviewQueue.type.obligationReview",
  evidence_review: "reviewQueue.type.evidenceReview",
  consent_change: "reviewQueue.type.consentChange",
};

const PRIORITY_LABEL: Readonly<Record<ReviewPriority, MessageKey>> = {
  high: "reviewQueue.priority.high",
  medium: "reviewQueue.priority.medium",
  low: "reviewQueue.priority.low",
};

const PRIORITY_TONE: Readonly<Record<ReviewPriority, Tone>> = {
  high: "danger",
  medium: "warning",
  low: "neutral",
};

export function reviewStatusLabel(status: ReviewStatus): string {
  return t(STATUS_LABEL[status]);
}

export function reviewStatusTone(status: ReviewStatus): Tone {
  return STATUS_TONE[status];
}

export function reviewTypeLabel(type: ReviewItemType): string {
  return t(TYPE_LABEL[type]);
}

export function reviewPriorityLabel(priority: ReviewPriority): string {
  return t(PRIORITY_LABEL[priority]);
}

export function reviewPriorityTone(priority: ReviewPriority): Tone {
  return PRIORITY_TONE[priority];
}

/** The status tabs, pending first because that is the work still to do. */
export function reviewStatusTabs(): SelectOption[] {
  return REVIEW_STATUSES.map((value) => ({ value, label: reviewStatusLabel(value) }));
}

export function reviewTypeOptions(): SelectOption[] {
  return REVIEW_ITEM_TYPES.map((value) => ({ value, label: reviewTypeLabel(value) }));
}

export function reviewCounts(items: readonly ReviewItem[]): ReviewCounts {
  const count = (status: ReviewStatus) => items.filter((item) => item.status === status).length;
  return {
    total: items.length,
    pending: count("pending"),
    approved: count("approved"),
    rejected: count("rejected"),
  };
}
