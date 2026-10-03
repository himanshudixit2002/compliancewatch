import type { Route } from "next";
import type { Tone } from "@compliancewatch/ui";

/** The value of a filter select that keeps every row. */
export const ALL = "all";

/** One error report, already worded for the table; the server view derives it from the model. */
export interface ReportRow {
  id: string;
  title: string;
  message: string;
  subject: string;
  /** Where an analyst reads the report, or null when the view was given no such page. */
  href: Route | null;
  severity: string;
  severityLabel: string;
  severityTone: Tone;
  status: string;
  statusLabel: string;
  statusTone: Tone;
  reportedLabel: string;
}

export interface ReportFilters {
  /** Matched, ignoring case, against the title and what the report is about. */
  search: string;
  /** A severity, or ALL. */
  severity: string;
  /** A status, or ALL. */
  status: string;
}

export const NO_REPORT_FILTERS: ReportFilters = { search: "", severity: ALL, status: ALL };

/** The rows that pass every filter, in their original order. */
export function filterReportRows(
  rows: readonly ReportRow[],
  filters: ReportFilters,
): readonly ReportRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (term === "" ||
        row.title.toLowerCase().includes(term) ||
        row.subject.toLowerCase().includes(term)) &&
      (filters.severity === ALL || row.severity === filters.severity) &&
      (filters.status === ALL || row.status === filters.status),
  );
}
