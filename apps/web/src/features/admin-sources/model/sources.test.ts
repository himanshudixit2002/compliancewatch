import { describe, expect, it } from "vitest";
import {
  SOURCE_STATUSES,
  canFetch,
  documentTypeLabel,
  formatCount,
  sourceCounts,
  sourceStatusLabel,
  sourceStatusTone,
  type PipelineSource,
  type SourceDocumentType,
} from "./sources";

function source(overrides: Partial<PipelineSource> = {}): PipelineSource {
  return {
    key: "cbic_notifications",
    name: "CBIC notifications",
    site: "taxinformation.cbic.gov.in",
    documentType: "notification",
    status: "healthy",
    lastFetchedAt: "2026-10-02T04:00:00Z",
    documentCount: 1200,
    ...overrides,
  };
}

describe("source labels and tones", () => {
  it("words and tones every status", () => {
    expect(SOURCE_STATUSES.map(sourceStatusLabel)).toEqual([
      "Healthy",
      "Fetching",
      "Failing",
      "Paused",
    ]);
    expect(SOURCE_STATUSES.map(sourceStatusTone)).toEqual(["success", "info", "danger", "neutral"]);
  });

  it("names every document type the rulebook knows", () => {
    const types: SourceDocumentType[] = [
      "notification",
      "circular",
      "press_release",
      "act_amendment",
    ];
    expect(types.map(documentTypeLabel)).toEqual([
      "Notifications",
      "Circulars",
      "Press releases",
      "Act amendments",
    ]);
  });
});

describe("formatCount", () => {
  it("groups digits the Indian way", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(1200)).toBe("1,200");
    expect(formatCount(1234567)).toBe("12,34,567");
  });
});

describe("canFetch", () => {
  it("allows a fetch unless one is already running", () => {
    expect(SOURCE_STATUSES.filter((status) => canFetch({ status }))).toEqual([
      "healthy",
      "failing",
      "paused",
    ]);
  });
});

describe("sourceCounts", () => {
  it("counts every source, the healthy ones and the failing ones", () => {
    expect(
      sourceCounts([
        source(),
        source({ key: "cbic_circulars", status: "failing" }),
        source({ key: "gstn_advisories", status: "paused" }),
        source({ key: "gstcouncil_press", status: "fetching" }),
      ]),
    ).toEqual({ total: 4, healthy: 1, failing: 1 });
    expect(sourceCounts([])).toEqual({ total: 0, healthy: 0, failing: 0 });
  });
});
