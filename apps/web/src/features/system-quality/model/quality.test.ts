import { describe, expect, it } from "vitest";
import {
  METRIC_STANDINGS,
  formatShare,
  metricStanding,
  qualitySummary,
  standingLabel,
  standingTone,
  type QualityMetric,
} from "./quality";

function metric(overrides: Partial<QualityMetric> = {}): QualityMetric {
  return {
    id: "q_recall",
    name: "Context recall",
    description: "Share of gold clauses present in the retrieved set.",
    value: 0.93,
    target: 0.92,
    ...overrides,
  };
}

describe("metricStanding", () => {
  it("meets the target at or above it, falls below it under it, and waits for a first run", () => {
    expect(metricStanding({ value: 0.93, target: 0.92 })).toBe("meets");
    expect(metricStanding({ value: 0.98, target: 0.98 })).toBe("meets");
    expect(metricStanding({ value: 0.951, target: 0.97 })).toBe("below");
    expect(metricStanding({ value: null, target: 0.95 })).toBe("unmeasured");
  });

  it("words and tones every standing", () => {
    expect(METRIC_STANDINGS.map(standingLabel)).toEqual([
      "Meets target",
      "Below target",
      "Not measured yet",
    ]);
    expect(METRIC_STANDINGS.map(standingTone)).toEqual(["success", "danger", "neutral"]);
  });
});

describe("formatShare", () => {
  it("shows a share as a percentage with at most one decimal place", () => {
    expect(formatShare(0.925)).toBe("92.5%");
    expect(formatShare(0.92)).toBe("92%");
    expect(formatShare(0.934)).toBe("93.4%");
    expect(formatShare(0.9999)).toBe("100%");
    expect(formatShare(1)).toBe("100%");
    expect(formatShare(0)).toBe("0%");
  });
});

describe("qualitySummary", () => {
  it("counts the measures and where each stands", () => {
    expect(
      qualitySummary([
        metric(),
        metric({ id: "2", value: 0.98, target: 0.98 }),
        metric({ id: "3", value: 0.5 }),
        metric({ id: "4", value: null }),
      ]),
    ).toEqual({ total: 4, meets: 2, below: 1, unmeasured: 1 });
    expect(qualitySummary([])).toEqual({ total: 0, meets: 0, below: 0, unmeasured: 0 });
  });
});
