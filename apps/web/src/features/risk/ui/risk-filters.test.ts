import { describe, expect, it } from "vitest";
import { ALL, filterRisks, type RiskRow } from "./risk-filters";

function row(overrides: Partial<RiskRow>): RiskRow {
  return {
    id: "1",
    title: "Late GST filing",
    description: "",
    href: "/b/biz_1/risk/1",
    severityLabel: "High",
    severityTone: "danger",
    status: "active",
    statusLabel: "Active",
    statusTone: "danger",
    likelihood: "40%",
    identifiedAt: "10 Apr 2026",
    owner: "Asha",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({ id: "2", title: "Missing consent", status: "mitigated", owner: "Ravi" }),
  row({ id: "3", title: "Expired licence", status: "closed" }),
];

const ids = (rows: readonly RiskRow[]) => rows.map((r) => r.id);

describe("filterRisks", () => {
  it("keeps every row for all statuses and no search", () => {
    expect(ids(filterRisks(ROWS, { status: ALL, search: "" }))).toEqual(["1", "2", "3"]);
  });

  it("narrows by status", () => {
    expect(ids(filterRisks(ROWS, { status: "closed", search: "" }))).toEqual(["3"]);
  });

  it("searches the title and the owner ignoring case", () => {
    expect(ids(filterRisks(ROWS, { status: ALL, search: " LICENCE " }))).toEqual(["3"]);
    expect(ids(filterRisks(ROWS, { status: ALL, search: "ravi" }))).toEqual(["2"]);
    expect(filterRisks(ROWS, { status: "active", search: "ravi" })).toEqual([]);
  });
});
