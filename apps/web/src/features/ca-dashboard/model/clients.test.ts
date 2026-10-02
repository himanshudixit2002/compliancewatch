import { describe, expect, it } from "vitest";
import {
  NO_FILTER,
  engagementTone,
  filterClients,
  isFiltered,
  parseClientFilter,
  summarizeClients,
  type CaClient,
} from "./clients";

const client = (overrides: Partial<CaClient>): CaClient => ({
  id: "c",
  name: "Client",
  engagementStatus: "active",
  complianceScore: null,
  obligationsDue: 0,
  obligationsOverdue: 0,
  assignedTo: null,
  updatedAt: "2026-10-01T09:00:00Z",
  ...overrides,
});

const clients = [
  client({ id: "a", name: "Acme Traders", complianceScore: 90, obligationsDue: 2 }),
  client({ id: "b", name: "Bright Foods", engagementStatus: "pending", complianceScore: 61 }),
  client({ id: "c", name: "Coastal Exports", engagementStatus: "inactive", obligationsOverdue: 3 }),
];

describe("parseClientFilter", () => {
  it("reads q and status, trimming the query and taking the first of repeated values", () => {
    expect(parseClientFilter({ q: "  acme ", status: "pending" })).toEqual({
      query: "acme",
      status: "pending",
    });
    expect(parseClientFilter({ q: ["foods", "x"], status: ["inactive"] })).toEqual({
      query: "foods",
      status: "inactive",
    });
  });

  it("falls back to no filter for missing or unknown values", () => {
    expect(parseClientFilter({})).toEqual(NO_FILTER);
    expect(parseClientFilter({ status: "archived" })).toEqual(NO_FILTER);
  });
});

describe("isFiltered", () => {
  it("is true when a query or a status is set", () => {
    expect(isFiltered(NO_FILTER)).toBe(false);
    expect(isFiltered({ query: "a", status: "all" })).toBe(true);
    expect(isFiltered({ query: "", status: "active" })).toBe(true);
  });
});

describe("filterClients", () => {
  it("matches the name in any case and the status", () => {
    expect(filterClients(clients, NO_FILTER)).toHaveLength(3);
    expect(filterClients(clients, { query: "FOODS", status: "all" }).map((c) => c.id)).toEqual([
      "b",
    ]);
    expect(filterClients(clients, { query: "", status: "inactive" }).map((c) => c.id)).toEqual([
      "c",
    ]);
    expect(filterClients(clients, { query: "acme", status: "pending" })).toEqual([]);
  });
});

describe("summarizeClients", () => {
  it("totals the counts and averages the scores clients have", () => {
    expect(summarizeClients(clients)).toEqual({
      total: 3,
      active: 1,
      due: 2,
      overdue: 3,
      averageScore: 76,
    });
  });

  it("has no average when no client has a score", () => {
    expect(summarizeClients([]).averageScore).toBeNull();
  });
});

describe("engagementTone", () => {
  it("maps each status to a tone", () => {
    expect(engagementTone("active")).toBe("success");
    expect(engagementTone("pending")).toBe("warning");
    expect(engagementTone("inactive")).toBe("neutral");
  });
});
