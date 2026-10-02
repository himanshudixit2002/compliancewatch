import { describe, expect, it } from "vitest";
import {
  REPORT_FORMATS,
  REPORT_STATUSES,
  downloadUrl,
  reportCounts,
  reportFormatLabel,
  reportFormatOptions,
  reportStatusLabel,
  reportStatusOptions,
  reportStatusTone,
  type ReportItem,
} from "./reports";

function report(overrides: Partial<ReportItem> = {}): ReportItem {
  return {
    id: "rep_1",
    name: "Quarterly compliance",
    format: "pdf",
    status: "ready",
    generatedAt: "2026-04-10T12:00:00Z",
    size: "1.2 MB",
    url: "https://files.example.com/rep_1.pdf",
    ...overrides,
  };
}

describe("report labels and tones", () => {
  it("words every format and status and tones every status", () => {
    expect(REPORT_FORMATS.map(reportFormatLabel)).toEqual(["PDF", "Excel", "CSV"]);
    expect(REPORT_STATUSES.map(reportStatusLabel)).toEqual(["Ready", "Generating", "Failed"]);
    expect(REPORT_STATUSES.map(reportStatusTone)).toEqual(["success", "warning", "danger"]);
    expect(reportFormatOptions()[1]).toEqual({ value: "xlsx", label: "Excel" });
    expect(reportStatusOptions().map((option) => option.value)).toEqual(REPORT_STATUSES);
  });
});

describe("downloadUrl", () => {
  it("offers a ready report's http or https address", () => {
    expect(downloadUrl(report())).toBe("https://files.example.com/rep_1.pdf");
    expect(downloadUrl(report({ url: "http://files.example.com/a.csv" }))).toBe(
      "http://files.example.com/a.csv",
    );
  });

  it("offers nothing for a report that is not ready, has no address or a non-web one", () => {
    expect(downloadUrl(report({ status: "generating" }))).toBeNull();
    expect(downloadUrl(report({ url: null }))).toBeNull();
    expect(downloadUrl(report({ url: "javascript:alert(1)" }))).toBeNull();
    expect(downloadUrl(report({ url: "not a url" }))).toBeNull();
  });
});

describe("reportCounts", () => {
  it("counts all, ready and generating reports", () => {
    expect(
      reportCounts([
        report(),
        report({ id: "2", status: "generating" }),
        report({ id: "3", status: "failed" }),
      ]),
    ).toEqual({ total: 3, ready: 1, generating: 1 });
  });
});
