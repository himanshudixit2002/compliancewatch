import { describe, expect, it } from "vitest";
import { ALL, NO_AUDIT_FILTERS, filterAuditRows, type AuditRow } from "./audit-filters";

function row(overrides: Partial<AuditRow>): AuditRow {
  return {
    id: "1",
    actor: "Example analyst",
    action: "user.disabled",
    category: "user",
    categoryLabel: "User",
    subjectType: "user",
    subjectId: "u_42",
    changes: [],
    at: "10 Apr 2000, 10:30 am IST",
    day: "2000-04-10",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({
    id: "2",
    actor: "rulebook",
    action: "rule.published",
    category: "rule",
    subjectId: "rv_7",
    day: "2000-04-11",
  }),
  row({
    id: "3",
    actor: "Example admin",
    action: "tenant.created",
    category: "tenant",
    day: "2000-04-12",
  }),
];

const ids = (rows: readonly AuditRow[]) => rows.map((item) => item.id);

describe("filterAuditRows", () => {
  it("keeps every row with no filter", () => {
    expect(ids(filterAuditRows(ROWS, NO_AUDIT_FILTERS))).toEqual(["1", "2", "3"]);
  });

  it("narrows by category", () => {
    expect(ids(filterAuditRows(ROWS, { ...NO_AUDIT_FILTERS, category: "rule" }))).toEqual(["2"]);
  });

  it("keeps the IST days from and to the dates chosen, both included", () => {
    expect(ids(filterAuditRows(ROWS, { ...NO_AUDIT_FILTERS, from: "2000-04-11" }))).toEqual([
      "2",
      "3",
    ]);
    expect(ids(filterAuditRows(ROWS, { ...NO_AUDIT_FILTERS, to: "2000-04-11" }))).toEqual([
      "1",
      "2",
    ]);
    expect(
      ids(filterAuditRows(ROWS, { ...NO_AUDIT_FILTERS, from: "2000-04-11", to: "2000-04-11" })),
    ).toEqual(["2"]);
  });

  it("searches the actor, the action and the record id, ignoring case and spaces", () => {
    expect(ids(filterAuditRows(ROWS, { ...NO_AUDIT_FILTERS, search: " ADMIN " }))).toEqual(["3"]);
    expect(ids(filterAuditRows(ROWS, { ...NO_AUDIT_FILTERS, search: "published" }))).toEqual(["2"]);
    expect(ids(filterAuditRows(ROWS, { ...NO_AUDIT_FILTERS, search: "u_42" }))).toEqual(["1", "3"]);
    expect(
      ids(filterAuditRows(ROWS, { search: "u_42", category: "tenant", from: "", to: "" })),
    ).toEqual(["3"]);
    expect(
      ids(filterAuditRows(ROWS, { ...NO_AUDIT_FILTERS, category: ALL, search: "no such text" })),
    ).toEqual([]);
  });
});
