import { describe, expect, it } from "vitest";
import {
  RISK_STATUSES,
  likelihoodText,
  riskCounts,
  riskSeverityLabel,
  riskSeverityTone,
  riskStatusLabel,
  riskStatusTabs,
  riskStatusTone,
  type RiskItem,
  type RiskSeverity,
} from "./risk";

function risk(overrides: Partial<RiskItem> = {}): RiskItem {
  return {
    id: "risk_1",
    title: "Late GST filing",
    description: "Penalty and interest.",
    severity: "high",
    status: "active",
    likelihood: 40,
    identifiedAt: "2026-04-10",
    owner: "Asha",
    ...overrides,
  };
}

const SEVERITIES: RiskSeverity[] = ["high", "medium", "low"];

describe("risk labels and tones", () => {
  it("words and tones every severity and status", () => {
    expect(SEVERITIES.map(riskSeverityLabel)).toEqual(["High", "Medium", "Low"]);
    expect(SEVERITIES.map(riskSeverityTone)).toEqual(["danger", "warning", "info"]);
    expect(RISK_STATUSES.map(riskStatusLabel)).toEqual(["Active", "Mitigated", "Closed"]);
    expect(RISK_STATUSES.map(riskStatusTone)).toEqual(["danger", "success", "neutral"]);
    expect(riskStatusTabs()[1]).toEqual({ value: "mitigated", label: "Mitigated" });
  });
});

describe("likelihoodText", () => {
  it("rounds to a whole percentage and keeps it within 0 to 100", () => {
    expect(likelihoodText(42.6)).toBe("43%");
    expect(likelihoodText(-5)).toBe("0%");
    expect(likelihoodText(140)).toBe("100%");
  });
});

describe("riskCounts", () => {
  it("counts all, high, medium and mitigated risks", () => {
    expect(
      riskCounts([
        risk(),
        risk({ id: "2", severity: "medium", status: "mitigated" }),
        risk({ id: "3", severity: "low", status: "closed" }),
      ]),
    ).toEqual({ total: 3, high: 1, medium: 1, mitigated: 1 });
  });
});
