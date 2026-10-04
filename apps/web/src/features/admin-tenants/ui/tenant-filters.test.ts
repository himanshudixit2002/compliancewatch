import { describe, expect, it } from "vitest";
import { ALL, NO_TENANT_FILTERS, filterTenants, type TenantRow } from "./tenant-filters";

function row(overrides: Partial<TenantRow>): TenantRow {
  return {
    id: "t1",
    name: "Example Traders",
    href: null,
    kind: "business",
    kindLabel: "Business",
    status: "active",
    statusLabel: "Active",
    statusTone: "success",
    region: "ap-south-1",
    created: "10 Apr 2000",
    impersonateHref: null,
    ...overrides,
  };
}

const ROWS = [
  row({ id: "t1" }),
  row({ id: "t2", name: "Example Firm & Co", kind: "ca_firm" }),
  row({ id: "a7-ops", name: "Regulatory team", kind: "internal" }),
];

const ids = (rows: readonly TenantRow[]) => rows.map((item) => item.id);

describe("filterTenants", () => {
  it("keeps every row with no filter", () => {
    expect(ids(filterTenants(ROWS, NO_TENANT_FILTERS))).toEqual(["t1", "t2", "a7-ops"]);
  });

  it("narrows by kind", () => {
    expect(ids(filterTenants(ROWS, { kind: "ca_firm", search: "" }))).toEqual(["t2"]);
    expect(ids(filterTenants(ROWS, { kind: "internal", search: "" }))).toEqual(["a7-ops"]);
  });

  it("searches the name and the id, ignoring case and surrounding spaces", () => {
    expect(ids(filterTenants(ROWS, { kind: ALL, search: "  FIRM " }))).toEqual(["t2"]);
    expect(ids(filterTenants(ROWS, { kind: ALL, search: "a7-" }))).toEqual(["a7-ops"]);
    expect(ids(filterTenants(ROWS, { kind: "business", search: "firm" }))).toEqual([]);
  });
});
