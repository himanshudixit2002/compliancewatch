import { describe, expect, it } from "vitest";
import {
  ALLOWED_ROLES,
  MFA_REQUIRED_ROLES,
  REGULATORY_ROLES,
  ROLES,
  TENANT_ADMIN_ROLES,
  TENANT_KINDS,
  TENANT_MEMBER_ROLES,
  firstRoleFor,
  hasRole,
  isRegulatory,
  isRole,
  isTenantKind,
  requiresMfa,
  tenantKindsFor,
} from "./roles.ts";

describe("roles", () => {
  it("lists the eight roles of the identity design in order", () => {
    expect(ROLES).toEqual([
      "owner",
      "staff",
      "ca_admin",
      "ca_staff",
      "compliance_lead",
      "analyst",
      "reviewer",
      "admin",
    ]);
    expect(isRole("partner")).toBe(false);
  });

  it("keeps the four role sets as the identity design defines them", () => {
    expect(TENANT_MEMBER_ROLES).toEqual([
      "owner",
      "staff",
      "ca_admin",
      "ca_staff",
      "compliance_lead",
    ]);
    expect(TENANT_ADMIN_ROLES).toEqual(["owner", "ca_admin"]);
    expect(REGULATORY_ROLES).toEqual(["analyst", "reviewer", "admin"]);
    expect(MFA_REQUIRED_ROLES).toEqual(["analyst", "reviewer", "admin", "ca_admin"]);
  });

  it("partitions the roles by tenant kind and names the first role of each", () => {
    expect(TENANT_KINDS).toEqual(["business", "ca_firm", "internal"]);
    const all = TENANT_KINDS.flatMap((kind) => ALLOWED_ROLES[kind]);
    expect(new Set(all)).toEqual(new Set(ROLES));
    expect(ALLOWED_ROLES.business).toEqual(["owner", "staff", "compliance_lead"]);
    expect(ALLOWED_ROLES.ca_firm).toEqual(["ca_admin", "ca_staff", "compliance_lead"]);
    expect(ALLOWED_ROLES.internal).toEqual(REGULATORY_ROLES);
    expect(firstRoleFor("business")).toBe("owner");
    expect(firstRoleFor("ca_firm")).toBe("ca_admin");
    expect(firstRoleFor("internal")).toBe("admin");
    expect(isTenantKind("internal")).toBe(true);
    expect(isTenantKind("partner")).toBe(false);
  });

  it("answers role questions for a principal and never for anonymous", () => {
    expect(hasRole({ roles: ["staff"] }, TENANT_MEMBER_ROLES)).toBe(true);
    expect(hasRole({ roles: ["staff"] }, REGULATORY_ROLES)).toBe(false);
    expect(hasRole(null, TENANT_MEMBER_ROLES)).toBe(false);
    expect(isRegulatory({ roles: ["reviewer"] })).toBe(true);
    expect(isRegulatory({ roles: ["owner"] })).toBe(false);
    expect(requiresMfa(["ca_admin"])).toBe(true);
    expect(requiresMfa(["owner", "staff"])).toBe(false);
  });

  it("finds the tenant kinds a role set belongs to", () => {
    expect(tenantKindsFor(["compliance_lead"])).toEqual(["business", "ca_firm"]);
    expect(tenantKindsFor(["admin"])).toEqual(["internal"]);
  });
});
