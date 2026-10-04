import { describe, expect, it } from "vitest";
import {
  TENANT_KINDS,
  TENANT_STATUSES,
  canImpersonate,
  sortTenants,
  tenantFromDto,
  tenantKindLabel,
  tenantKindTabs,
  tenantStatusLabel,
  tenantStatusTone,
  tenantsSummary,
  type Tenant,
  type TenantDto,
} from "./admin-tenants";

function tenant(overrides: Partial<Tenant> = {}): Tenant {
  return {
    id: "t1",
    name: "Example Traders",
    kind: "business",
    status: "active",
    region: "ap-south-1",
    createdAt: "2000-04-10T05:00:00Z",
    ...overrides,
  };
}

describe("tenantFromDto", () => {
  it("keeps the identity service's fields under the screen's names", () => {
    const dto: TenantDto = {
      id: "6f1c2b9e-0d4a-4c1e-9a53-2f0b7f9d1e21",
      name: "Example Firm & Co",
      kind: "ca_firm",
      status: "deletion_requested",
      region: "ap-south-1",
      created_at: "2000-05-02T05:00:00Z",
    };
    expect(tenantFromDto(dto)).toEqual({
      id: "6f1c2b9e-0d4a-4c1e-9a53-2f0b7f9d1e21",
      name: "Example Firm & Co",
      kind: "ca_firm",
      status: "deletion_requested",
      region: "ap-south-1",
      createdAt: "2000-05-02T05:00:00Z",
    });
  });
});

describe("tenant labels and tones", () => {
  it("words every kind and status, and tones each status", () => {
    expect(TENANT_KINDS.map(tenantKindLabel)).toEqual([
      "Business",
      "CA firm",
      "Internal (regulatory team)",
    ]);
    expect(TENANT_STATUSES.map(tenantStatusLabel)).toEqual([
      "Active",
      "Deletion requested",
      "Erased",
    ]);
    expect(TENANT_STATUSES.map(tenantStatusTone)).toEqual(["success", "warning", "neutral"]);
  });

  it("builds one tab per kind", () => {
    expect(tenantKindTabs()).toEqual([
      { value: "business", label: "Business" },
      { value: "ca_firm", label: "CA firm" },
      { value: "internal", label: "Internal (regulatory team)" },
    ]);
  });
});

describe("canImpersonate", () => {
  it("offers impersonation for active business and CA firm tenants only", () => {
    expect(canImpersonate(tenant())).toBe(true);
    expect(canImpersonate(tenant({ kind: "ca_firm" }))).toBe(true);
    expect(canImpersonate(tenant({ kind: "internal" }))).toBe(false);
    expect(canImpersonate(tenant({ status: "deletion_requested" }))).toBe(false);
    expect(canImpersonate(tenant({ status: "erased" }))).toBe(false);
  });
});

describe("sortTenants", () => {
  it("orders the tenants by name and leaves the input as it was", () => {
    const input = [
      tenant({ id: "3", name: "Example business C" }),
      tenant({ id: "1", name: "Example business A" }),
      tenant({ id: "2", name: "Example business B" }),
    ];
    expect(sortTenants(input).map((item) => item.id)).toEqual(["1", "2", "3"]);
    expect(input.map((item) => item.id)).toEqual(["3", "1", "2"]);
  });
});

describe("tenantsSummary", () => {
  it("counts every tenant and each status", () => {
    expect(
      tenantsSummary([
        tenant(),
        tenant({ id: "2", kind: "internal" }),
        tenant({ id: "3", status: "deletion_requested" }),
        tenant({ id: "4", status: "erased" }),
        tenant({ id: "5", status: "erased" }),
      ]),
    ).toEqual({ total: 5, active: 2, deletionRequested: 1, erased: 2 });
    expect(tenantsSummary([])).toEqual({ total: 0, active: 0, deletionRequested: 0, erased: 0 });
  });
});
