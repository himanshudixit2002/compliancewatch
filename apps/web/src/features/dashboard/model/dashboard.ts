import type { Tone } from "@compliancewatch/ui";
import { dueRelative } from "@/shared/lib/dates";

/** One business on the dashboard, with its obligation counts. */
export interface DashboardBusiness {
  id: string;
  name: string;
  openObligations: number;
  overdueObligations: number;
}

/** Something that happened recently; the list is newest first. */
export interface DashboardActivity {
  id: string;
  description: string;
  /** The instant it happened (ISO 8601). */
  at: string;
}

/** An obligation due soon or overdue, linked to its page. */
export interface UrgentAction {
  businessId: string;
  obligationId: string;
  title: string;
  /** The due date as a date key ("2026-10-20"). */
  dueDate: string;
}

/** The owner's compliance overview across their businesses. */
export interface DashboardSummary {
  overdue: number;
  dueThisWeek: number;
  completed: number;
  businesses: readonly DashboardBusiness[];
  activities: readonly DashboardActivity[];
  urgentActions: readonly UrgentAction[];
}

export function emptyDashboard(): DashboardSummary {
  return {
    overdue: 0,
    dueThisWeek: 0,
    completed: 0,
    businesses: [],
    activities: [],
    urgentActions: [],
  };
}

/** Completed obligations as a whole percentage of all counted ones; null when none are counted. */
export function completionRate(view: DashboardSummary): number | null {
  const total = view.completed + view.overdue + view.dueThisWeek;
  return total === 0 ? null : Math.round((view.completed / total) * 100);
}

export function completionTone(rate: number | null): Tone {
  if (rate === null) return "neutral";
  if (rate >= 80) return "success";
  if (rate >= 50) return "warning";
  return "danger";
}

/** A business with anything overdue needs attention; otherwise it is up to date. */
export function businessTone(business: DashboardBusiness): Tone {
  return business.overdueObligations > 0 ? "danger" : "success";
}

/** Overdue actions are danger, the rest warning, relative to today in IST. */
export function urgentTone(action: UrgentAction, now: Date = new Date()): Tone {
  return dueRelative(action.dueDate, now).kind === "overdue" ? "danger" : "warning";
}
