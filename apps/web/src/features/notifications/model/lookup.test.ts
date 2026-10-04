import { describe, expect, it } from "vitest";
import { readLookup, readTenant } from "./lookup";

const TENANT = "00000000-0000-4000-8000-0000000000a1";
const BUSINESS = "00000000-0000-4000-8000-0000000000b1";

describe("readLookup", () => {
  it("is empty before anything is asked, and reads the tenant and business, lower-cased", () => {
    expect(readLookup({})).toEqual({ kind: "empty" });
    expect(readLookup({ tenant: " ", business: "" })).toEqual({ kind: "empty" });
    expect(readLookup({ tenant: TENANT.toUpperCase(), business: [BUSINESS, "x"] })).toEqual({
      kind: "ok",
      lookup: { tenantId: TENANT, businessId: BUSINESS },
    });
  });

  it("says which id is not one, keeping what was typed", () => {
    expect(readLookup({ tenant: "not-a-tenant", business: BUSINESS })).toEqual({
      kind: "invalid",
      values: { tenant: "not-a-tenant", business: BUSINESS },
      errors: { tenant: "Enter the tenant's id, a UUID." },
    });
    expect(readLookup({ tenant: TENANT })).toEqual({
      kind: "invalid",
      values: { tenant: TENANT, business: "" },
      errors: { business: "Enter the business's id, a UUID." },
    });
  });
});

describe("readTenant", () => {
  it("reads the tenant a notification belongs to", () => {
    expect(readTenant({})).toEqual({ kind: "empty" });
    expect(readTenant({ tenant: TENANT })).toEqual({ kind: "ok", tenantId: TENANT });
    expect(readTenant({ tenant: "nope" })).toEqual({
      kind: "invalid",
      value: "nope",
      error: "Enter the tenant's id, a UUID.",
    });
  });
});
