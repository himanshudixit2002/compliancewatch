import type { SelectOption, Tone } from "@compliancewatch/ui";
import type { obligation } from "@compliancewatch/contracts/openapi";
import { t, type MessageKey } from "@/shared/i18n";
import { addDaysToKey, dueRelative, formatDate, istDateKey } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";

/**
 * The obligation screens' model: a business's obligations as `GET /v1/obligation/obligations`
 * returns them (ObligationOut), with the labels, tones and due-date wording the views use.
 * Dates are judged in India: an obligation is due by the end of its due day in IST.
 */
export type ObligationDto = obligation.components["schemas"]["ObligationOut"];
export type ObligationStatus = obligation.components["schemas"]["ObligationStatus"];
export type ClosureReason = obligation.components["schemas"]["ClosureReason"];

export const OBLIGATION_STATUSES: readonly ObligationStatus[] = [
  "open",
  "in_progress",
  "done",
  "waived",
  "closed_not_applicable",
];

/** One duty of a business, for one period when its rule recurs. */
export interface Obligation {
  id: string;
  businessId: string;
  title: string;
  status: ObligationStatus;
  /** The end of the due day in India, as an instant; null when the rule sets no due date. */
  dueAt: string | null;
  /** What proves it was met, as a code such as "filing_acknowledgement"; empty when unnamed. */
  evidenceType: string;
  /** What to do, in order. */
  steps: readonly string[];
  ruleVersionId: string;
  decisionId: string;
  /** The period's label ("2026-09", "2026-27 Q2"); null for a duty that does not recur. */
  periodLabel: string | null;
  /** The period's first day, a date key. */
  periodStart: string | null;
  /** The day after the period's last day, a date key: the period is half-open. */
  periodEnd: string | null;
  closedAt: string | null;
  closedReason: ClosureReason | null;
  /** The profile version of the decision that made it; null for one made before it was kept. */
  profileVersion: number | null;
  /** The user of the tenant it is given to; null for nobody. */
  assigneeId: string | null;
}

/** The figures in the list's summary row. */
export interface ObligationCounts {
  total: number;
  open: number;
  inProgress: number;
  overdue: number;
  done: number;
}

/** The statuses a person moves an obligation to from its page. */
export type ObligationStatusChange = Extract<ObligationStatus, "in_progress" | "done">;

/** The status form's field names, shared with the server action that reads them. */
export const OBLIGATION_STATUS_FIELDS = { status: "status" } as const;

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

const CHANGE_LABEL: Readonly<Record<ObligationStatusChange, MessageKey>> = {
  in_progress: "obligations.action.start",
  done: "obligations.action.done",
};

export function obligationFromDto(dto: ObligationDto): Obligation {
  return {
    id: dto.obligation_id,
    businessId: dto.business_id,
    title: dto.title,
    status: dto.status,
    dueAt: dto.due_at,
    evidenceType: dto.evidence_type,
    steps: dto.steps,
    ruleVersionId: dto.rule_version_id,
    decisionId: dto.decision_id,
    periodLabel: dto.period_label,
    periodStart: dto.period_start,
    periodEnd: dto.period_end,
    closedAt: dto.closed_at,
    closedReason: dto.closed_reason,
    profileVersion: dto.profile_version,
    assigneeId: dto.assignee_id,
  };
}

export function obligationStatusLabel(status: ObligationStatus): string {
  return t(STATUS_LABEL[status]);
}

export function obligationStatusTone(status: ObligationStatus): Tone {
  return STATUS_TONE[status];
}

export function closureReasonLabel(reason: ClosureReason): string {
  return t(CLOSURE_LABEL[reason]);
}

export function statusChangeLabel(change: ObligationStatusChange): string {
  return t(CHANGE_LABEL[change]);
}

export function obligationStatusOptions(): SelectOption[] {
  return OBLIGATION_STATUSES.map((value) => ({ value, label: obligationStatusLabel(value) }));
}

/** Open and in-progress obligations still need doing; the other statuses are final. */
export function isObligationActive(status: ObligationStatus): boolean {
  return status === "open" || status === "in_progress";
}

/** The moves the obligation's page offers: start an open one, mark an active one done. */
export function statusChanges(status: ObligationStatus): readonly ObligationStatusChange[] {
  if (status === "open") return ["in_progress", "done"];
  if (status === "in_progress") return ["done"];
  return [];
}

/** The due day in India (a date key) of a due instant. */
function dueDay(dueAt: string): string {
  return istDateKey(new Date(dueAt));
}

/** An obligation still to be done whose due day in India is before today. */
export function isObligationOverdue(item: Obligation, now: Date = new Date()): boolean {
  return (
    item.dueAt !== null &&
    isObligationActive(item.status) &&
    dueRelative(dueDay(item.dueAt), now).kind === "overdue"
  );
}

/** "20 Oct 2026", or that the rule sets no due date. */
export function dueDateText(item: Obligation): string {
  return item.dueAt === null ? t("obligations.noDueDate") : formatDate(item.dueAt);
}

/**
 * How the due day relates to today in India ("Due in 3 days", "Overdue by 2 days") for an
 * obligation still to be done; null when it is closed or has no due date.
 */
export function duePhrase(item: Obligation, now: Date = new Date()): string | null {
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
export function periodText(item: Obligation): string | null {
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

export function obligationCounts(
  items: readonly Obligation[],
  now: Date = new Date(),
): ObligationCounts {
  const count = (status: ObligationStatus) => items.filter((item) => item.status === status).length;
  return {
    total: items.length,
    open: count("open"),
    inProgress: count("in_progress"),
    overdue: items.filter((item) => isObligationOverdue(item, now)).length,
    done: count("done"),
  };
}
