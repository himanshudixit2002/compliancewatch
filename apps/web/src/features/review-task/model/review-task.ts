import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";
import {
  type ReviewItemType,
  type ReviewPriority,
  type ReviewStatus,
} from "../review-queue";

/**
 * The admin review-workbench domain: a single item the queue lists, with an assignee and the
 * structured metadata the backend stores with every task (node, financial year, reason for the
 * task, which document triggered it, and a free-form payload the API may add later).
 */
export interface ReviewTask {
  /** Immutable identifier assigned when the task enters the queue. */
  id: string;
  /** The category of work the reviewer is being asked to do. */
  type: ReviewItemType;
  /** Where the task sits in the lifecycle. */
  status: ReviewStatus;
  /** How urgently the task needs a decision. */
  priority: ReviewPriority;
  /** The internal user id of whoever is working on it, empty while unassigned. */
  assignee: string;
  /** A short human-readable heading for the card and the page header. */
  title: string;
  /** One to three sentences explaining why the task was created. */
  description: string;
  /** When the task was created, an ISO-8601 instant. */
  createdAt: string;
  /** The SLA target, an ISO-8601 instant. */
  dueAt: string;
  /** Backend-supplied structured data: the node id, financial year, the reason code, any
   *  related document id, and an extensible payload. */
  metadata: ReviewTaskMetadata;
}

/**
 * The structured payload attached to every review task by the backend.  Each field is optional
 * because different task types populate different parts of it.
 */
export interface ReviewTaskMetadata {
  /** The ontology node this task relates to, when applicable. */
  nodeId?: string;
  /** The financial year the question covers, if set. */
  financialYear?: string;
  /** Why the task was opened: one of the well-known reason codes. */
  reason?: string;
  /** The pipeline document that triggered the task, when there is one. */
  documentId?: string;
  /** Extra fields the backend may add without changing the API contract. */
  [key: string]: unknown;
}

/**
 * Data a presentational component needs, separated from the raw domain object so the UI layer
 * does not need to know which status codes exist or how they are labelled.
 */
export interface ReviewTaskView {
  task: ReviewTask;
  /** Actions the current user may take on this task, in priority order. */
  actions: ReviewTaskAction[];
}

/**
 * One discrete action the reviewer can take on the workbench.
 */
export interface ReviewTaskAction {
  /** Stable slug used for the button id and aria attributes. */
  id: string;
  /** The label shown on the button. */
  label: string;
  /** How prominent the action looks: primary for approve, danger for reject, secondary otherwise. */
  tone?: "primary" | "secondary" | "danger";
  /** Whether the action requires a reason before it fires. */
  requiresReason?: boolean;
}

/** A fresh, empty task used as a placeholder before the real one loads. */
export function emptyReviewTask(): ReviewTask {
  return {
    id: "",
    type: "attribute_change",
    status: "pending",
    priority: "medium",
    assignee: "",
    title: "",
    description: "",
    createdAt: "",
    dueAt: "",
    metadata: {},
  };
}

const STATUS_LABEL: Readonly<Record<ReviewStatus, MessageKey>> = {
  pending: "reviewTask.status.pending",
  approved: "reviewTask.status.approved",
  rejected: "reviewTask.status.rejected",
};

const STATUS_TONE: Readonly<Record<ReviewStatus, Tone>> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
};

/**
 * The display label for a status, passed through t() so it participates in the i18n pipeline.
 * Keys live under `reviewTask.status.*` in the messages file.
 */
export function reviewTaskStatusLabel(status: ReviewStatus): string {
  return t(STATUS_LABEL[status]);
}

/**
 * The visual tone for a status badge: yellow for pending, green for approved, red for rejected.
 * Kept in the model so the UI does not hard-code the mapping.
 */
export function reviewTaskStatusTone(status: ReviewStatus): Tone {
  return STATUS_TONE[status];
}
