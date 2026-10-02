import { describe, expect, it } from "vitest";
import { evidenceTone, formatFileSize } from "./evidence";

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

describe("evidenceTone", () => {
  it("maps each status to a tone", () => {
    expect(evidenceTone("submitted")).toBe("info");
    expect(evidenceTone("accepted")).toBe("success");
    expect(evidenceTone("rejected")).toBe("danger");
  });
});
