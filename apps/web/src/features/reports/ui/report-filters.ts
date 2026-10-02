import type { Tone } from "@compliancewatch/ui";

/** The value of a filter select that keeps every row. */
export const ALL = "all";

/** One report, already worded for the table; the server view derives it from the model. */
export interface ReportRow {
  id: string;
  name: string;
  format: string;
  formatLabel: string;
  status: string;
  statusLabel: string;
  statusTone: Tone;
  generatedAt: string;
  size: string;
  downloadUrl: string | null;
}

export interface ReportFilters {
  /** Matched, ignoring case, against the report's name. */
  search: string;
  /** A format, or ALL. */
  format: string;
  /** A status, or ALL. */
  status: string;
}

export const NO_REPORT_FILTERS: ReportFilters = { search: "", format: ALL, status: ALL };

/** The rows that pass every filter, in their original order. */
export function filterReports(
  rows: readonly ReportRow[],
  filters: ReportFilters,
): readonly ReportRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (term === "" || row.name.toLowerCase().includes(term)) &&
      (filters.format === ALL || row.format === filters.format) &&
      (filters.status === ALL || row.status === filters.status),
  );
}
