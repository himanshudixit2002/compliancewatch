import { describe, expect, it } from "vitest";
import {
  ERROR_REPORT_STATUSES,
  ERROR_SEVERITIES,
  isUrgent,
  reportCounts,
  reportStatusLabel,
  reportStatusOptions,
  reportStatusTone,
  severityLabel,
  severityOptions,
  severityTone,
  sortReports,
  type ErrorReport,
} from "./error-reports";

function report(overrides: Partial<ErrorReport> = {}): ErrorReport {
  return {
    id: "err_1",
    title: "Wrong due date for GSTR-3B",
    message: "The obligation says the 20th but the notification moved it to the 22nd.",
    subject: "GSTR-3B monthly return",
    severity: "medium",
    status: "open",
    reportedAt: "2026-10-01T05:00:00Z",
    ...overrides,
  };
}

describe("report labels and tones", () => {
  it("words and tones every severity, most serious first", () => {
    expect(ERROR_SEVERITIES.map(severityLabel)).toEqual(["Critical", "High", "Medium", "Low"]);
    expect(ERROR_SEVERITIES.map(severityTone)).toEqual(["danger", "danger", "warning", "info"]);
    expect(severityOptions()[0]).toEqual({ value: "critical", label: "Critical" });
  });

  it("words and tones every status", () => {
    expect(ERROR_REPORT_STATUSES.map(reportStatusLabel)).toEqual(["Open", "Resolved", "Dismissed"]);
    expect(ERROR_REPORT_STATUSES.map(reportStatusTone)).toEqual(["warning", "success", "neutral"]);
    expect(reportStatusOptions().map((option) => option.value)).toEqual(ERROR_REPORT_STATUSES);
  });
});

describe("isUrgent", () => {
  it("is true only for an open report that is critical or high", () => {
    expect(isUrgent({ status: "open", severity: "critical" })).toBe(true);
    expect(isUrgent({ status: "open", severity: "high" })).toBe(true);
    expect(isUrgent({ status: "open", severity: "medium" })).toBe(false);
    expect(isUrgent({ status: "resolved", severity: "critical" })).toBe(false);
  });
});

describe("sortReports", () => {
  it("puts open reports first, then the most serious, then the earliest reported", () => {
    const reports = [
      report({ id: "dismissed", status: "dismissed", severity: "critical" }),
      report({ id: "resolved", status: "resolved", severity: "low" }),
      report({ id: "open-low", severity: "low" }),
      report({
        id: "open-critical-late",
        severity: "critical",
        reportedAt: "2026-10-02T05:00:00Z",
      }),
      report({
        id: "open-critical-early",
        severity: "critical",
        reportedAt: "2026-10-02T09:00:00+05:30",
      }),
      report({ id: "open-medium" }),
    ];
    expect(sortReports(reports).map((entry) => entry.id)).toEqual([
      "open-critical-early",
      "open-critical-late",
      "open-medium",
      "open-low",
      "resolved",
      "dismissed",
    ]);
    expect(reports[0]?.id).toBe("dismissed");
  });
});

describe("reportCounts", () => {
  it("counts every report, the open ones, the urgent ones and the resolved ones", () => {
    expect(
      reportCounts([
        report({ severity: "critical" }),
        report({ id: "2", severity: "low" }),
        report({ id: "3", severity: "high", status: "resolved" }),
        report({ id: "4", status: "dismissed" }),
      ]),
    ).toEqual({ total: 4, open: 2, urgent: 1, resolved: 1 });
    expect(reportCounts([])).toEqual({ total: 0, open: 0, urgent: 0, resolved: 0 });
  });
});
