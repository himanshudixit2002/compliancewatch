import { describe, expect, it } from "vitest";
import { ALL, NO_REPORT_FILTERS, filterReports, type ReportRow } from "./report-filters";

function row(overrides: Partial<ReportRow>): ReportRow {
  return {
    id: "1",
    name: "Quarterly compliance",
    format: "pdf",
    formatLabel: "PDF",
    status: "ready",
    statusLabel: "Ready",
    statusTone: "success",
    generatedAt: "10 Apr 2026",
    size: "1 MB",
    downloadUrl: null,
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({ id: "2", name: "GST summary", format: "xlsx" }),
  row({ id: "3", name: "GST detail", format: "xlsx", status: "failed" }),
];

const ids = (rows: readonly ReportRow[]) => rows.map((r) => r.id);

describe("filterReports", () => {
  it("keeps every row with no filters", () => {
    expect(ids(filterReports(ROWS, NO_REPORT_FILTERS))).toEqual(["1", "2", "3"]);
  });

  it("searches the name ignoring case, and narrows by format and status together", () => {
    expect(ids(filterReports(ROWS, { ...NO_REPORT_FILTERS, search: " gst " }))).toEqual(["2", "3"]);
    expect(ids(filterReports(ROWS, { search: "", format: "xlsx", status: ALL }))).toEqual([
      "2",
      "3",
    ]);
    expect(ids(filterReports(ROWS, { search: "", format: "xlsx", status: "ready" }))).toEqual([
      "2",
    ]);
    expect(filterReports(ROWS, { search: "", format: "csv", status: ALL })).toEqual([]);
  });
});
