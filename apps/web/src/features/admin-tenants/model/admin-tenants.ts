import type { SelectOption, Tone } from "@compliancewatch/ui";
import type { identity } from "@compliancewatch/contracts/openapi";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The tenants screen's model: every tenant as the identity service describes one (`TenantOut`;
 * the admin listing, `GET /v1/identity/admin/tenants`, is still to come), with the labels and
 * tones the table and the summary row use.
 */
export type TenantDto = identity.components["schemas"]["TenantOut"];
export type TenantKind = identity.components["schemas"]["TenantKind"];
export type TenantStatus = identity.components["schemas"]["TenantStatus"];

export const TENANT_KINDS: readonly TenantKind[] = ["business", "ca_firm", "internal"];

export const TENANT_STATUSES: readonly TenantStatus[] = ["active", "deletion_requested", "erased"];

export interface Tenant {
  id: string;
  name: string;
  kind: TenantKind;
  status: TenantStatus;
  /** Where the tenant's data is kept, for example "ap-south-1". */
  region: string;
  /** When the tenant signed up, an ISO instant. */
  createdAt: string;
}

/** The figures in the summary row. */
export interface TenantsSummary {
  total: number;
  active: number;
  deletionRequested: number;
  erased: number;
}

const KIND_LABEL: Readonly<Record<TenantKind, MessageKey>> = {
  business: "tenantKind.business",
  ca_firm: "tenantKind.ca_firm",
  internal: "tenantKind.internal",
};

const STATUS_LABEL: Readonly<Record<TenantStatus, MessageKey>> = {
  active: "adminTenants.status.active",
  deletion_requested: "adminTenants.status.deletionRequested",
  erased: "adminTenants.status.erased",
};

const STATUS_TONE: Readonly<Record<TenantStatus, Tone>> = {
  active: "success",
  deletion_requested: "warning",
  erased: "neutral",
};

export function tenantFromDto(dto: TenantDto): Tenant {
  return {
    id: dto.id,
    name: dto.name,
    kind: dto.kind,
    status: dto.status,
    region: dto.region,
    createdAt: dto.created_at,
  };
}

export function tenantKindLabel(kind: TenantKind): string {
  return t(KIND_LABEL[kind]);
}

export function tenantStatusLabel(status: TenantStatus): string {
  return t(STATUS_LABEL[status]);
}

export function tenantStatusTone(status: TenantStatus): Tone {
  return STATUS_TONE[status];
}

/** One tab per tenant kind, in the order the identity service lists them. */
export function tenantKindTabs(): SelectOption[] {
  return TENANT_KINDS.map((value) => ({ value, label: tenantKindLabel(value) }));
}

/**
 * Impersonation is offered for active business and CA firm tenants only: the internal tenant is
 * the admins' own, and a tenant whose deletion was requested or carried out is left alone.
 */
export function canImpersonate(tenant: Pick<Tenant, "kind" | "status">): boolean {
  return tenant.status === "active" && tenant.kind !== "internal";
}

/** Tenants by name, the order the table lists them in. */
export function sortTenants(tenants: readonly Tenant[]): Tenant[] {
  return [...tenants].sort((a, b) => a.name.localeCompare(b.name));
}

export function tenantsSummary(tenants: readonly Tenant[]): TenantsSummary {
  const count = (status: TenantStatus) =>
    tenants.filter((tenant) => tenant.status === status).length;
  return {
    total: tenants.length,
    active: count("active"),
    deletionRequested: count("deletion_requested"),
    erased: count("erased"),
  };
}
