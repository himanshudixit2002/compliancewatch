import type { SelectOption, Tone } from "@compliancewatch/ui";
import {
  OBLIGATION_STATUSES,
  type ClosureReason,
  type Obligation,
  type ObligationStatus,
  type RuleVersionFacts,
  type StatusAction,
} from "@/entities/obligation/types";
import { t, type MessageKey } from "@/shared/i18n";
import { addDaysToKey, dueRelative, formatDate, istDateKey } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";

/**
 * The words the obligation screens use for an obligation: its status and closure, how its due day
 * relates to today, its period and the evidence it needs, the status changes its status allows,
 * and the review state of the rule it comes from. Dates are judged in India: an obligation is due
 * by the end of its due day in IST.
 */
const STATUS_LABEL: Readonly<Record<ObligationStatus, MessageKey>> = {
  open: "obligations.status.open",
  in_progress: "obligations.status.inProgress",
  done: "obligations.status.done",
  waived: "obligations.status.waived",
  closed_not_applicable: "obligations.status.notApplicable",
};

const STATUS_TONE: Readonly<Record<ObligationStatus, Tone>> = {
  open: "info",
  in_progress: "warning",
  done: "success",
  waived: "neutral",
  closed_not_applicable: "neutral",
};

const CLOSURE_LABEL: Readonly<Record<ClosureReason, MessageKey>> = {
  completed: "obligations.closure.completed",
  waived_by_user: "obligations.closure.waivedByUser",
  profile_changed: "obligations.closure.profileChanged",
  rule_withdrawn: "obligations.closure.ruleWithdrawn",
  rule_superseded: "obligations.closure.ruleSuperseded",
};

const ACTION_LABEL: Readonly<Record<StatusAction, MessageKey>> = {
  start: "obligations.action.start",
  complete: "obligations.action.complete",
  waive: "obligations.action.waive",
};

export function obligationStatusLabel(status: ObligationStatus): string {
  return t(STATUS_LABEL[status]);
}

export function obligationStatusTone(status: ObligationStatus): Tone {
  return STATUS_TONE[status];
}

export function closureReasonLabel(reason: ClosureReason): string {
  return t(CLOSURE_LABEL[reason]);
}

export function statusActionLabel(action: StatusAction): string {
  return t(ACTION_LABEL[action]);
}

/** Open and in-progress obligations still need doing; the other statuses are final. */
export function isObligationActive(status: ObligationStatus): boolean {
  return status === "open" || status === "in_progress";
}

/**
 * What a member may do from the obligation's page, as the service allows it: start an open one,
 * complete or waive one still to do. A closed obligation takes no status change (a 409).
 */
export function statusActions(status: ObligationStatus): readonly StatusAction[] {
  if (status === "open") return ["start", "complete", "waive"];
  if (status === "in_progress") return ["complete", "waive"];
  return [];
}

/** The due day in India (a date key) of a due instant. */
export function dueDay(dueAt: string): string {
  return istDateKey(new Date(dueAt));
}

/** An obligation still to be done whose due day in India is before today. */
export function isObligationOverdue(
  item: Pick<Obligation, "dueAt" | "status">,
  now: Date = new Date(),
): boolean {
  return (
    item.dueAt !== null &&
    isObligationActive(item.status) &&
    dueRelative(dueDay(item.dueAt), now).kind === "overdue"
  );
}

/** "20 Oct 2026", or that the rule sets no due date. */
export function dueDateText(item: Pick<Obligation, "dueAt">): string {
  return item.dueAt === null ? t("obligations.noDueDate") : formatDate(dueDay(item.dueAt));
}

/**
 * How the due day relates to today in India ("Due in 3 days", "Overdue by 2 days") for an
 * obligation still to be done; null when it is closed or has no due date.
 */
export function duePhrase(
  item: Pick<Obligation, "dueAt" | "status">,
  now: Date = new Date(),
): string | null {
  if (item.dueAt === null || !isObligationActive(item.status)) return null;
  const relative = dueRelative(dueDay(item.dueAt), now);
  switch (relative.kind) {
    case "today":
      return t("obligations.due.today");
    case "tomorrow":
      return t("obligations.due.tomorrow");
    case "in_days":
      return t("obligations.due.inDays", { count: relative.days });
    case "overdue":
      return relative.days === 1
        ? t("obligations.due.overdueDay")
        : t("obligations.due.overdueDays", { count: relative.days });
  }
}

/**
 * "Period 2026-09: 1 Sep 2026 to 30 Sep 2026" (the end is the day before the half-open period
 * ends), the label alone when the service gives no dates, or null for a one-off duty.
 */
export function periodText(
  item: Pick<Obligation, "periodLabel" | "periodStart" | "periodEnd">,
): string | null {
  if (item.periodLabel === null) return null;
  if (item.periodStart === null || item.periodEnd === null) {
    return t("obligations.periodLabel", { label: item.periodLabel });
  }
  return t("obligations.period", {
    label: item.periodLabel,
    start: formatDate(item.periodStart),
    end: formatDate(addDaysToKey(item.periodEnd, -1)),
  });
}

/** "Filing acknowledgement" for "filing_acknowledgement"; says so when the rule names none. */
export function evidenceTypeText(evidenceType: string): string {
  return evidenceType.trim() === ""
    ? t("obligations.evidence.unspecified")
    : humanise(evidenceType);
}

/** "Completed on 10 Oct 2026"; the date alone when the service names no reason. */
export function closedText(item: Pick<Obligation, "closedAt" | "closedReason">): string | null {
  if (item.closedAt === null) return null;
  const date = formatDate(item.closedAt);
  return item.closedReason === null
    ? date
    : t("obligations.closedOn", { reason: closureReasonLabel(item.closedReason), date });
}

/** The status filter's choices: every status, the ones still to do, then each status. */
export const ALL_STATUSES = "all";
export const TO_DO = "todo";

export type StatusFilter = typeof ALL_STATUSES | typeof TO_DO | ObligationStatus;

export function isStatusFilter(value: string): value is StatusFilter {
  return (
    value === ALL_STATUSES ||
    value === TO_DO ||
    (OBLIGATION_STATUSES as readonly string[]).includes(value)
  );
}

/** The statuses a filter keeps, as the service's repeated `status` parameter; none for all. */
export function statusesOf(filter: StatusFilter): readonly ObligationStatus[] {
  if (filter === ALL_STATUSES) return [];
  if (filter === TO_DO) return ["open", "in_progress"];
  return [filter];
}

export function statusFilterOptions(): SelectOption[] {
  return [
    { value: ALL_STATUSES, label: t("obligations.filter.allStatuses") },
    { value: TO_DO, label: t("obligations.filter.toDo") },
    ...OBLIGATION_STATUSES.map((status) => ({
      value: status,
      label: obligationStatusLabel(status),
    })),
  ];
}

/** Whether the rule behind an obligation was reviewed, as a short label and a tone. */
export interface ReviewState {
  reviewed: boolean;
  label: string;
  tone: Tone;
}

/**
 * A seed rule reads needs_review until an analyst has checked it against its source; a rule
 * version the service has not kept yet (null) is unknown, and says so rather than guessing.
 */
export function reviewState(facts: RuleVersionFacts | null): ReviewState {
  if (facts === null) {
    return { reviewed: false, label: t("obligations.review.unknown"), tone: "neutral" };
  }
  return facts.reviewed
    ? { reviewed: true, label: t("obligations.review.reviewed"), tone: "success" }
    : { reviewed: false, label: t("obligations.review.notReviewed"), tone: "warning" };
}
