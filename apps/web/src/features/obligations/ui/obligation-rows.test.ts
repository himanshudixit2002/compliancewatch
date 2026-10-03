import { describe, expect, it } from "vitest";
import {
  ALL,
  NO_OBLIGATION_FILTERS,
  OVERDUE,
  filterObligations,
  type ObligationRow,
} from "./obligation-rows";

function row(overrides: Partial<ObligationRow>): ObligationRow {
  return {
    id: "1",
    title: "File example return 1 for the month",
    href: "/b/biz_1/obligations/1",
    period: "Period 2000-09: 1 Sept 2000 to 30 Sept 2000",
    status: "open",
    statusLabel: "Open",
    statusTone: "info",
    due: "20 Oct 2000",
    dueNote: "Due in 5 days",
    overdue: false,
    evidence: "Filing acknowledgement",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({ id: "2", title: "Pay example tax", status: "in_progress", overdue: true, period: null }),
  row({ id: "3", title: "File example return 2", status: "done", period: "Period 2000-08" }),
];

const ids = (rows: readonly ObligationRow[]) => rows.map((r) => r.id);

describe("filterObligations", () => {
  it("keeps every row, in order, without filters", () => {
    expect(ids(filterObligations(ROWS, NO_OBLIGATION_FILTERS))).toEqual(["1", "2", "3"]);
  });

  it("narrows by status, or to the overdue rows", () => {
    expect(ids(filterObligations(ROWS, { status: "done", search: "" }))).toEqual(["3"]);
    expect(ids(filterObligations(ROWS, { status: OVERDUE, search: "" }))).toEqual(["2"]);
    expect(filterObligations(ROWS, { status: "waived", search: "" })).toEqual([]);
  });

  it("searches the title and the period ignoring case and surrounding space", () => {
    expect(ids(filterObligations(ROWS, { status: ALL, search: "  EXAMPLE RETURN " }))).toEqual([
      "1",
      "3",
    ]);
    expect(ids(filterObligations(ROWS, { status: ALL, search: "2000-08" }))).toEqual(["3"]);
    expect(ids(filterObligations(ROWS, { status: ALL, search: "tax" }))).toEqual(["2"]);
    expect(ids(filterObligations(ROWS, { status: "open", search: "example return" }))).toEqual([
      "1",
    ]);
  });
});
