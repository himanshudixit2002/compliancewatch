import type { Route } from "next";
import type { Tone } from "@compliancewatch/ui";

/** The value of a filter select that keeps every row. */
export const ALL = "all";

/** One change, already worded for the list; the server view derives it from the model. */
export interface ChangeRow {
  id: string;
  title: string;
  regulator: string;
  summary: string;
  href: Route;
  applicability: string;
  applicabilityLabel: string;
  applicabilityTone: Tone;
  reviewStatus: string;
  reviewLabel: string;
  reviewTone: Tone;
  facts: readonly string[];
  categories: readonly string[];
}

export interface ChangeFilters {
  /** Matched, ignoring case, against the title and the regulator. */
  search: string;
  /** An applicability value, or ALL. */
  applicability: string;
  /** A review status, or ALL. */
  reviewStatus: string;
}

export const NO_CHANGE_FILTERS: ChangeFilters = {
  search: "",
  applicability: ALL,
  reviewStatus: ALL,
};

/** The rows that pass every filter, in their original order. */
export function filterChanges(
  rows: readonly ChangeRow[],
  filters: ChangeFilters,
): readonly ChangeRow[] {
  const term = filters.search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (term === "" ||
        row.title.toLowerCase().includes(term) ||
        row.regulator.toLowerCase().includes(term)) &&
      (filters.applicability === ALL || row.applicability === filters.applicability) &&
      (filters.reviewStatus === ALL || row.reviewStatus === filters.reviewStatus),
  );
}
