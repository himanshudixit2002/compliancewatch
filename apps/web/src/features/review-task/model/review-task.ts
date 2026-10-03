import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The review workbench's model: one task from the operations team's review queue, with its
 * assignee and the structured metadata stored with it. The rulebook's review-task routes are
 * not specified yet (WP21), so these types are the screen's own.
 */
export type ReviewTaskType =
  "attribute_change" | "obligation_review" | "evidence_review" | "consent_change";

/** Where the task stands: waiting for a decision, or decided. */
export type ReviewTaskStatus = "pending" | "approved" | "rejected";

export type ReviewTaskPriority = "high" | "medium" | "low";

/** What a reviewer decides on a pending task; a rejection carries a reason. */
export type ReviewDecision = "approve" | "reject";

/** The structured data stored with a task; each task type fills in different parts. */
export interface ReviewTaskMetadata {
  /** The ontology node the task is about. */
  nodeId?: string;
  /** The financial year the question covers, such as "2026-27". */
  financialYear?: string;
  /** Why the task was opened, as a reason code such as "low_confidence". */
  reason?: string;
  /** The pipeline document that opened the task. */
  documentId?: string;
}

export interface ReviewTask {
  id: string;
  type: ReviewTaskType;
  status: ReviewTaskStatus;
  priority: ReviewTaskPriority;
  /** Who is working on it; null while unassigned. */
  assignee: string | null;
  /** A short heading for the page. */
  title: string;
  /** One to three sentences on why the task exists. */
  description: string;
  /** When the task entered the queue, an instant. */
  createdAt: string;
  /** The service-level target, an instant; null when none is set. */
  dueAt: string | null;
  metadata: ReviewTaskMetadata;
}

/** The decision form's field names, shared with the server action that reads them. */
export const REVIEW_DECISION_FIELDS = { decision: "decision", reason: "reason" } as const;

const STATUS_LABEL: Readonly<Record<ReviewTaskStatus, MessageKey>> = {
  pending: "reviewTask.status.pending",
  approved: "reviewTask.status.approved",
  rejected: "reviewTask.status.rejected",
};

const STATUS_TONE: Readonly<Record<ReviewTaskStatus, Tone>> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
};

const TYPE_LABEL: Readonly<Record<ReviewTaskType, MessageKey>> = {
  attribute_change: "reviewTask.type.attributeChange",
  obligation_review: "reviewTask.type.obligationReview",
  evidence_review: "reviewTask.type.evidenceReview",
  consent_change: "reviewTask.type.consentChange",
};

const PRIORITY_LABEL: Readonly<Record<ReviewTaskPriority, MessageKey>> = {
  high: "reviewTask.priority.high",
  medium: "reviewTask.priority.medium",
  low: "reviewTask.priority.low",
};

const PRIORITY_TONE: Readonly<Record<ReviewTaskPriority, Tone>> = {
  high: "danger",
  medium: "warning",
  low: "neutral",
};

export function reviewTaskStatusLabel(status: ReviewTaskStatus): string {
  return t(STATUS_LABEL[status]);
}

export function reviewTaskStatusTone(status: ReviewTaskStatus): Tone {
  return STATUS_TONE[status];
}

export function reviewTaskTypeLabel(type: ReviewTaskType): string {
  return t(TYPE_LABEL[type]);
}

export function reviewTaskPriorityLabel(priority: ReviewTaskPriority): string {
  return t(PRIORITY_LABEL[priority]);
}

export function reviewTaskPriorityTone(priority: ReviewTaskPriority): Tone {
  return PRIORITY_TONE[priority];
}

/** A pending task whose due instant has passed; a decided task is never past due. */
export function isPastDue(task: ReviewTask, now: Date = new Date()): boolean {
  return task.status === "pending" && task.dueAt !== null && Date.parse(task.dueAt) < now.getTime();
}
