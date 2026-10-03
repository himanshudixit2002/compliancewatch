import type { Route } from "next";
import type { Tone } from "@compliancewatch/ui";

/** The status filter value that keeps every row. */
export const ALL = "all";

/** The status filter value that keeps the obligations past their due day. */
export const OVERDUE = "overdue";

/** One obligation, already worded for the table; the server view derives it from the model. */
export interface ObligationRow {
  id: string;
  title: string;
  href: Route;
  /** The period worded with its dates; null for a one-off duty. */
  period: string | null;
  status: string;
  statusLabel: string;
  statusTone: Tone;
  /** The due date, or that there is none. */
  due: string;
  /** How the due day relates to today; null once closed or without a due date. */
  dueNote: string | null;
  overdue: boolean;
  evidence: string;
}

export interface ObligationFilters {
  /** A status, OVERDUE or ALL. */
  status: string;
  /** Matched, ignoring case, against the title and the period. */
  search: string;
}

export const NO_OBLIGATION_FILTERS: ObligationFilters = { status: ALL, search: "" };

function matchesStatus(row: ObligationRow, status: string): boolean {
  if (status === ALL) return true;
  if (status === OVERDUE) return row.overdue;
  return row.status === status;
}

/** The rows that pass every filter, in their original (due date) order. */
export function filterObligations(
  rows: readonly ObligationRow[],
  filters: ObligationFilters,
): readonly ObligationRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      matchesStatus(row, filters.status) &&
      (term === "" ||
        row.title.toLowerCase().includes(term) ||
        (row.period ?? "").toLowerCase().includes(term)),
  );
}
