import { describe, expect, it } from "vitest";
import { ALL, NO_REPORT_FILTERS, filterReportRows, type ReportRow } from "./report-filters";

function row(overrides: Partial<ReportRow>): ReportRow {
  return {
    id: "1",
    title: "Wrong due date for example return 1",
    message: "The notification moved it to the 22nd.",
    subject: "Example monthly return",
    href: null,
    severity: "high",
    severityLabel: "High",
    severityTone: "danger",
    status: "open",
    statusLabel: "Open",
    statusTone: "warning",
    reportedLabel: "1 Oct 2000, 10:30 am IST",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({
    id: "2",
    title: "Example rate is out of date",
    subject: "Example tax on rent",
    severity: "low",
  }),
  row({ id: "3", title: "Missing late fee", subject: "Example return 2", status: "resolved" }),
];

const ids = (rows: readonly ReportRow[]) => rows.map((r) => r.id);

describe("filterReportRows", () => {
  it("keeps every row with no filters", () => {
    expect(ids(filterReportRows(ROWS, NO_REPORT_FILTERS))).toEqual(["1", "2", "3"]);
  });

  it("searches the title and the subject, ignoring case and outer spaces", () => {
    expect(ids(filterReportRows(ROWS, { ...NO_REPORT_FILTERS, search: "  LATE fee " }))).toEqual([
      "3",
    ]);
    expect(ids(filterReportRows(ROWS, { ...NO_REPORT_FILTERS, search: "on rent" }))).toEqual(["2"]);
    expect(filterReportRows(ROWS, { ...NO_REPORT_FILTERS, search: "22nd" })).toEqual([]);
  });

  it("narrows by severity and by status together", () => {
    expect(ids(filterReportRows(ROWS, { search: "", severity: "high", status: ALL }))).toEqual([
      "1",
      "3",
    ]);
    expect(
      ids(filterReportRows(ROWS, { search: "", severity: "high", status: "resolved" })),
    ).toEqual(["3"]);
    expect(ids(filterReportRows(ROWS, { search: "", severity: ALL, status: "open" }))).toEqual([
      "1",
      "2",
    ]);
  });
});
