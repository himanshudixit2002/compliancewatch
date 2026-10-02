import { describe, expect, it } from "vitest";
import { ALL_ROLES, filterMembers } from "./member-filter";
import type { MemberRow } from "./member-filter";

function row(id: string, name: string, email: string, roles: string[]): MemberRow {
  return {
    id,
    name,
    email,
    roles: roles.map((value) => ({ value, label: value, tone: "neutral" })),
    status: { value: "active", label: "Active", tone: "success" },
    joined: "1 Jan 2026",
  };
}

const ROWS = [
  row("1", "Meera Iyer", "meera@example.com", ["admin"]),
  row("2", "Kabir Shah", "kabir@corp.example", ["analyst", "reviewer"]),
  row("3", "Lata Menon", "lata@example.com", []),
];

const ids = (rows: MemberRow[]) => rows.map((r) => r.id);

describe("filterMembers", () => {
  it("returns everyone with an empty query and every role", () => {
    expect(ids(filterMembers(ROWS, "", ALL_ROLES))).toEqual(["1", "2", "3"]);
    expect(ids(filterMembers(ROWS, "   ", ALL_ROLES))).toEqual(["1", "2", "3"]);
  });

  it("matches the name or the email, ignoring case and surrounding spaces", () => {
    expect(ids(filterMembers(ROWS, " MEERA ", ALL_ROLES))).toEqual(["1"]);
    expect(ids(filterMembers(ROWS, "corp.example", ALL_ROLES))).toEqual(["2"]);
    expect(ids(filterMembers(ROWS, "nobody", ALL_ROLES))).toEqual([]);
  });

  it("keeps only members holding the chosen role, combined with the query", () => {
    expect(ids(filterMembers(ROWS, "", "reviewer"))).toEqual(["2"]);
    expect(ids(filterMembers(ROWS, "meera", "reviewer"))).toEqual([]);
    expect(ids(filterMembers(ROWS, "kabir", "analyst"))).toEqual(["2"]);
  });
});
