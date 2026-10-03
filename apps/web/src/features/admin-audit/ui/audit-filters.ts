/** The category select's value that keeps every event. */
export const ALL = "all";

/** One audit event, already worded for the table; the server view derives it from the model. */
export interface AuditRow {
  id: string;
  actor: string;
  action: string;
  category: string;
  categoryLabel: string;
  subjectType: string;
  subjectId: string;
  /** Each changed field in words; empty when the event changed none. */
  changes: readonly string[];
  /** When it happened, formatted in IST. */
  at: string;
  /** The IST date it happened on, YYYY-MM-DD, for the date range. */
  day: string;
}

export interface AuditFilters {
  /** Matched, ignoring case and surrounding spaces, against the actor, action and record id. */
  search: string;
  /** A category, or ALL. */
  category: string;
  /** The first IST date to keep, YYYY-MM-DD, or "" for no lower bound. */
  from: string;
  /** The last IST date to keep, YYYY-MM-DD, or "" for no upper bound. */
  to: string;
}

export const NO_AUDIT_FILTERS: AuditFilters = { search: "", category: ALL, from: "", to: "" };

/** The rows that pass every filter, in their original order. */
export function filterAuditRows(
  rows: readonly AuditRow[],
  filters: AuditFilters,
): readonly AuditRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (filters.category === ALL || row.category === filters.category) &&
      (filters.from === "" || row.day >= filters.from) &&
      (filters.to === "" || row.day <= filters.to) &&
      (term === "" ||
        [row.actor, row.action, row.subjectId].some((text) => text.toLowerCase().includes(term))),
  );
}
