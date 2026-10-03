import { describe, expect, it } from "vitest";
import { ALL, filterEvidenceRows, type EvidenceRow } from "./evidence-rows";

function row(overrides: Partial<EvidenceRow>): EvidenceRow {
  return {
    id: "e1",
    fileName: "challan.pdf",
    size: "1.5 KB",
    uploadedBy: "Priya Shah",
    uploadedAt: "2026-10-01T09:00:00Z",
    uploadedLabel: "1 Oct 2026, 2:30 pm IST",
    status: "submitted",
    statusLabel: "Submitted",
    statusTone: "info",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "e1" }),
  row({ id: "e2", status: "accepted" }),
  row({ id: "e3", status: "submitted" }),
];

const ids = (rows: readonly EvidenceRow[]) => rows.map((r) => r.id);

describe("filterEvidenceRows", () => {
  it("keeps every file, in order, for ALL", () => {
    expect(filterEvidenceRows(ROWS, ALL)).toBe(ROWS);
  });

  it("keeps the files with the chosen review status", () => {
    expect(ids(filterEvidenceRows(ROWS, "submitted"))).toEqual(["e1", "e3"]);
    expect(ids(filterEvidenceRows(ROWS, "accepted"))).toEqual(["e2"]);
    expect(filterEvidenceRows(ROWS, "rejected")).toEqual([]);
  });
});
