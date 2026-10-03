import type { SelectOption, Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The Q&A triage queue: questions the answering service did not cover and answers people marked
 * as unhelpful, waiting for an analyst. `GET /v1/eval/triage` has no committed spec yet, so these
 * are plain types; instants are ISO strings and the views format them in IST.
 */

/** Why a question reached triage. */
export type TriageReason = "not_covered" | "thumbs_down";

/** Where an item stands: waiting for an analyst, or decided. */
export type TriageStatus = "open" | "closed";

export type TriagePriority = "high" | "medium" | "low";

export const TRIAGE_STATUSES: readonly TriageStatus[] = ["open", "closed"];

export const TRIAGE_REASONS: readonly TriageReason[] = ["not_covered", "thumbs_down"];

export const TRIAGE_PRIORITIES: readonly TriagePriority[] = ["high", "medium", "low"];

/** One question in the triage queue. */
export interface TriageItem {
  id: string;
  /** The question as it was asked. */
  question: string;
  /** The topic it is filed under, such as "GST returns". */
  category: string;
  reason: TriageReason;
  priority: TriagePriority;
  status: TriageStatus;
  /** The analyst who picked it up; null while nobody has. */
  assignee: string | null;
  /** When it entered the queue. */
  createdAt: string;
}

/** The figures in the summary row. */
export interface TriageCounts {
  total: number;
  open: number;
  closed: number;
}

const REASON_LABEL: Readonly<Record<TriageReason, MessageKey>> = {
  not_covered: "adminQaTriage.reason.notCovered",
  thumbs_down: "adminQaTriage.reason.thumbsDown",
};

const STATUS_LABEL: Readonly<Record<TriageStatus, MessageKey>> = {
  open: "adminQaTriage.status.open",
  closed: "adminQaTriage.status.closed",
};

const STATUS_TONE: Readonly<Record<TriageStatus, Tone>> = {
  open: "warning",
  closed: "success",
};

const PRIORITY_LABEL: Readonly<Record<TriagePriority, MessageKey>> = {
  high: "adminQaTriage.priority.high",
  medium: "adminQaTriage.priority.medium",
  low: "adminQaTriage.priority.low",
};

const PRIORITY_TONE: Readonly<Record<TriagePriority, Tone>> = {
  high: "danger",
  medium: "warning",
  low: "neutral",
};

export function triageReasonLabel(reason: TriageReason): string {
  return t(REASON_LABEL[reason]);
}

export function triageStatusLabel(status: TriageStatus): string {
  return t(STATUS_LABEL[status]);
}

export function triageStatusTone(status: TriageStatus): Tone {
  return STATUS_TONE[status];
}

export function triagePriorityLabel(priority: TriagePriority): string {
  return t(PRIORITY_LABEL[priority]);
}

export function triagePriorityTone(priority: TriagePriority): Tone {
  return PRIORITY_TONE[priority];
}

export function triageStatusOptions(): SelectOption[] {
  return TRIAGE_STATUSES.map((value) => ({ value, label: triageStatusLabel(value) }));
}

export function triageReasonOptions(): SelectOption[] {
  return TRIAGE_REASONS.map((value) => ({ value, label: triageReasonLabel(value) }));
}

/** Open items first, then the higher priority, then the one that has waited longest. */
export function sortTriageItems(items: readonly TriageItem[]): TriageItem[] {
  return [...items].sort((a, b) => {
    if (a.status !== b.status) return a.status === "open" ? -1 : 1;
    if (a.priority !== b.priority) {
      return TRIAGE_PRIORITIES.indexOf(a.priority) - TRIAGE_PRIORITIES.indexOf(b.priority);
    }
    return Date.parse(a.createdAt) - Date.parse(b.createdAt);
  });
}

export function triageCounts(items: readonly TriageItem[]): TriageCounts {
  const open = items.filter((item) => item.status === "open").length;
  return { total: items.length, open, closed: items.length - open };
}
