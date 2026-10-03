import type { Tone } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { MessageKey } from "@/shared/i18n";

export const TENANT_KIND = ["business", "ca_firm"] as const;

export type TenantKind = (typeof TENANT_KIND)[number];

export const TENANT_STATUS = ["active", "inactive", "suspended"] as const;

export type TenantStatus = (typeof TENANT_STATUS)[number];

export interface Tenant {
  id: string;
  name: string;
  kind: TenantKind;
  status: TenantStatus;
  /** When the tenant was created, an ISO instant. */
  createdAt: string;
  /** When the tenant was last updated, an ISO instant. */
  updatedAt: string;
  /** Number of members in the tenant. */
  memberCount: number;
  /** Overall compliance score as a percentage 0-100. */
  complianceScore: number;
}

export type TenantFilter = "all" | TenantKind;

export interface AdminTenantsView {
  tenants: readonly Tenant[];
  totalCount: number;
  filter: TenantFilter;
  sort: string;
}

/** The totals the summary row reads. */
export interface AdminTenantsSummary {
  total: number;
  active: number;
  suspended: number;
}

export const TENANT_STATUS_LABEL: Readonly<Record<TenantStatus, MessageKey>> = {
  active: "adminTenants.status.active",
  inactive: "adminTenants.status.inactive",
  suspended: "adminTenants.status.suspended",
};

export const TENANT_STATUS_TONE: Readonly<Record<TenantStatus, Tone>> = {
  active: "success",
  inactive: "neutral",
  suspended: "warning",
};

export const TENANT_KIND_LABEL: Readonly<Record<TenantKind, MessageKey>> = {
  business: "tenantKind.business",
  ca_firm: "tenantKind.ca_firm",
};

export const TENANT_KIND_TONE: Readonly<Record<TenantKind, Tone>> = {
  business: "info",
  ca_firm: "warning",
};

export function emptyAdminTenants(): AdminTenantsView {
  return {
    tenants: [],
    totalCount: 0,
    filter: "all",
    sort: "name",
  };
}

/** The totals the summary row reads. */
export function adminTenantsSummary(tenants: readonly Tenant[]): AdminTenantsSummary {
  let active = 0;
  let suspended = 0;
  for (const tenant of tenants) {
    if (tenant.status === "active") active += 1;
    if (tenant.status === "suspended") suspended += 1;
  }
  return { total: tenants.length, active, suspended };
}

/** The status badge's label in the user's language. */
export function tenantStatusLabel(status: TenantStatus): string {
  return t(TENANT_STATUS_LABEL[status]);
}

/** The kind badge's label in the user's language. */
export function tenantKindLabel(kind: TenantKind): string {
  return t(TENANT_KIND_LABEL[kind]);
}

/** The tone the status badge takes; active is success, suspended is warning, inactive is neutral. */
export function tenantStatusTone(status: TenantStatus): Tone {
  return TENANT_STATUS_TONE[status];
}

/** The tone the kind badge takes; business is info, CA firm is warning. */
export function tenantKindTone(kind: TenantKind): Tone {
  return TENANT_KIND_TONE[kind];
}
