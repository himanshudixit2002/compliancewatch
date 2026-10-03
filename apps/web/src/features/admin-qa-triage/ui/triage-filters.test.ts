import { describe, expect, it } from "vitest";
import { ALL, NO_TRIAGE_FILTERS, filterTriageRows, type TriageRow } from "./triage-filters";

function row(overrides: Partial<TriageRow>): TriageRow {
  return {
    id: "1",
    question: "When is GSTR-3B due for March?",
    category: "GST returns",
    href: null,
    reason: "not_covered",
    reasonLabel: "Not covered",
    priorityLabel: "High",
    priorityTone: "danger",
    status: "open",
    statusLabel: "Open",
    statusTone: "warning",
    assignee: "Unassigned",
    createdLabel: "1 Oct 2026, 10:30 am IST",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({ id: "2", question: "Is TDS due on rent?", category: "TDS", reason: "thumbs_down" }),
  row({ id: "3", question: "Who files ITC-04?", category: "Job work", status: "closed" }),
];

const ids = (rows: readonly TriageRow[]) => rows.map((r) => r.id);

describe("filterTriageRows", () => {
  it("keeps every row with no filters", () => {
    expect(ids(filterTriageRows(ROWS, NO_TRIAGE_FILTERS))).toEqual(["1", "2", "3"]);
  });

  it("searches the question and the topic, ignoring case and outer spaces", () => {
    expect(ids(filterTriageRows(ROWS, { ...NO_TRIAGE_FILTERS, search: "  RENT " }))).toEqual(["2"]);
    expect(ids(filterTriageRows(ROWS, { ...NO_TRIAGE_FILTERS, search: "job work" }))).toEqual([
      "3",
    ]);
    expect(filterTriageRows(ROWS, { ...NO_TRIAGE_FILTERS, search: "nothing" })).toEqual([]);
  });

  it("narrows by status and by reason together", () => {
    expect(ids(filterTriageRows(ROWS, { search: "", status: "open", reason: ALL }))).toEqual([
      "1",
      "2",
    ]);
    expect(
      ids(filterTriageRows(ROWS, { search: "", status: "open", reason: "thumbs_down" })),
    ).toEqual(["2"]);
    expect(ids(filterTriageRows(ROWS, { search: "", status: ALL, reason: "not_covered" }))).toEqual(
      ["1", "3"],
    );
  });
});
