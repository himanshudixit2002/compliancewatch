import type { Route } from "next";
import type { Tone } from "@compliancewatch/ui";

/** The value of a filter select that keeps every row. */
export const ALL = "all";

/** One triage item, already worded for the table; the server view derives it from the model. */
export interface TriageRow {
  id: string;
  question: string;
  category: string;
  /** Where an analyst reviews the item, or null when the view was given no such page. */
  href: Route | null;
  reason: string;
  reasonLabel: string;
  priorityLabel: string;
  priorityTone: Tone;
  status: string;
  statusLabel: string;
  statusTone: Tone;
  /** The analyst's name, or the word for nobody. */
  assignee: string;
  createdLabel: string;
}

export interface TriageFilters {
  /** Matched, ignoring case, against the question and its topic. */
  search: string;
  /** A status, or ALL. */
  status: string;
  /** A reason, or ALL. */
  reason: string;
}

export const NO_TRIAGE_FILTERS: TriageFilters = { search: "", status: ALL, reason: ALL };

/** The rows that pass every filter, in their original order. */
export function filterTriageRows(
  rows: readonly TriageRow[],
  filters: TriageFilters,
): readonly TriageRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (term === "" ||
        row.question.toLowerCase().includes(term) ||
        row.category.toLowerCase().includes(term)) &&
      (filters.status === ALL || row.status === filters.status) &&
      (filters.reason === ALL || row.reason === filters.reason),
  );
}
