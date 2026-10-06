import { describe, expect, it } from "vitest";
import { REVIEWED_TENANT_ID } from "@/test/engine-admin-fixture";
import { isStatusFilter, lookupHref, readDecisionLookup, statusFilterLabel } from "./lookup";

describe("the decision review lookup", () => {
  it("asks for nothing before a tenant is given, and keeps the status", () => {
    expect(readDecisionLookup({})).toEqual({ kind: "empty", status: "open" });
    expect(readDecisionLookup({ status: "resolved" })).toEqual({
      kind: "empty",
      status: "resolved",
    });
  });

  it("refuses a tenant that is not a UUID, keeping what was typed", () => {
    expect(readDecisionLookup({ tenant: " Not-A-Tenant ", status: "all" })).toEqual({
      kind: "invalid",
      value: "not-a-tenant",
      error: "Enter the tenant's id, a UUID.",
      status: "all",
    });
  });

  it("reads the tenant, the status (open unless known) and a cursor the engine could write", () => {
    expect(
      readDecisionLookup({
        tenant: REVIEWED_TENANT_ID.toUpperCase(),
        status: "nonsense",
        cursor: "abc_DEF-1",
      }),
    ).toEqual({ kind: "ok", tenantId: REVIEWED_TENANT_ID, status: "open", cursor: "abc_DEF-1" });
    expect(
      readDecisionLookup({ tenant: [REVIEWED_TENANT_ID], cursor: "bad cursor!" }),
    ).toMatchObject({
      kind: "ok",
      cursor: null,
    });
    expect(
      readDecisionLookup({ tenant: REVIEWED_TENANT_ID, cursor: "x".repeat(513) }),
    ).toMatchObject({
      cursor: null,
    });
  });

  it("writes the address with the default status left out", () => {
    expect(lookupHref("/admin/decisions", REVIEWED_TENANT_ID, "open")).toBe(
      `/admin/decisions?tenant=${REVIEWED_TENANT_ID}`,
    );
    expect(lookupHref("/admin/decisions", REVIEWED_TENANT_ID, "all", "next-1")).toBe(
      `/admin/decisions?tenant=${REVIEWED_TENANT_ID}&status=all&cursor=next-1`,
    );
    expect(statusFilterLabel("all")).toBe("Every item");
    expect(isStatusFilter("resolved")).toBe(true);
    expect(isStatusFilter("closed")).toBe(false);
  });
});
