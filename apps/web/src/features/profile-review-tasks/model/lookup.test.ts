import { describe, expect, it } from "vitest";
import { REGISTRATION_ID, TENANT_ID } from "@/test/business-fixture";
import { lookupHref, readLookup } from "./lookup";

const NOW = new Date("2000-06-15T00:00:00Z");

describe("readLookup", () => {
  it("asks nothing before a lookup, with this financial year ready", () => {
    expect(readLookup({}, NOW)).toEqual({ kind: "empty", fy: "2000-01" });
  });

  it("reads a tenant, a node and a year", () => {
    expect(
      readLookup({ tenant: TENANT_ID.toUpperCase(), node: REGISTRATION_ID, fy: "1999-00" }, NOW),
    ).toEqual({ kind: "ok", tenantId: TENANT_ID, nodeId: REGISTRATION_ID, fy: "1999-00" });
    expect(readLookup({ tenant: TENANT_ID, node: REGISTRATION_ID }, NOW)).toMatchObject({
      kind: "ok",
      fy: "2000-01",
    });
  });

  it("names each field it cannot use", () => {
    expect(readLookup({ tenant: "x", node: "", fy: "2000" }, NOW)).toEqual({
      kind: "invalid",
      values: { tenant: "x", node: "", fy: "2000" },
      errors: {
        tenant: "This is not a tenant id (a UUID).",
        node: "This is not a node id (a UUID): a business, a registration or a location.",
        fy: "Give the year as 2026-27.",
      },
    });
  });
});

describe("lookupHref", () => {
  it("puts the lookup in the address", () => {
    expect(lookupHref("/admin/profiles/review-tasks", TENANT_ID, REGISTRATION_ID, "2000-01")).toBe(
      `/admin/profiles/review-tasks?tenant=${TENANT_ID}&node=${REGISTRATION_ID}&fy=2000-01`,
    );
  });
});
