import { describe, expect, it } from "vitest";
import {
  EVIDENCE_STATUSES,
  evidenceCounts,
  evidenceStatusLabel,
  evidenceStatusTabs,
  evidenceTone,
  formatFileSize,
  type EvidenceItem,
} from "./evidence";

function item(overrides: Partial<EvidenceItem> = {}): EvidenceItem {
  return {
    id: "e1",
    fileName: "challan.pdf",
    sizeBytes: 1536,
    uploadedBy: "Priya Shah",
    uploadedAt: "2026-10-01T09:00:00Z",
    status: "submitted",
    ...overrides,
  };
}

describe("formatFileSize", () => {
  it("uses binary multiples with at most one decimal", () => {
    expect(formatFileSize(0)).toBe("0 B");
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(2 * 1024 * 1024)).toBe("2 MB");
    expect(formatFileSize(3.25 * 1024 ** 3)).toBe("3.3 GB");
  });

  it("caps at GB and treats a negative size as zero", () => {
    expect(formatFileSize(2048 * 1024 ** 3)).toBe("2048 GB");
    expect(formatFileSize(-5)).toBe("0 B");
  });
});

describe("evidence labels and tones", () => {
  it("words and tones each review status", () => {
    expect(EVIDENCE_STATUSES.map(evidenceStatusLabel)).toEqual([
      "Submitted",
      "Accepted",
      "Rejected",
    ]);
    expect(EVIDENCE_STATUSES.map(evidenceTone)).toEqual(["info", "success", "danger"]);
  });

  it("builds one tab per review status, in review order", () => {
    expect(evidenceStatusTabs()).toEqual([
      { value: "submitted", label: "Submitted" },
      { value: "accepted", label: "Accepted" },
      { value: "rejected", label: "Rejected" },
    ]);
  });
});

describe("evidenceCounts", () => {
  it("counts every file and each review status", () => {
    expect(
      evidenceCounts([
        item(),
        item({ id: "e2", status: "accepted" }),
        item({ id: "e3", status: "accepted" }),
        item({ id: "e4", status: "rejected" }),
      ]),
    ).toEqual({ total: 4, submitted: 1, accepted: 2, rejected: 1 });
  });

  it("is all zeros without files", () => {
    expect(evidenceCounts([])).toEqual({ total: 0, submitted: 0, accepted: 0, rejected: 0 });
  });
});
