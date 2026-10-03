import type { Route } from "next";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  canImpersonate,
  sortTenants,
  tenantKindLabel,
  tenantKindTabs,
  tenantStatusLabel,
  tenantStatusTone,
  tenantsSummary,
  type Tenant,
} from "../model/admin-tenants";
import type { TenantRow } from "./tenant-filters";
import { TenantsTable } from "./tenants-table";

export interface AdminTenantsViewProps {
  tenants: readonly Tenant[];
  /** A tenant's own page; without it the names are plain text. */
  hrefFor?: (tenantId: string) => Route;
  /** Where an admin starts a read-only impersonation; without it none is offered. */
  impersonateHref?: (tenantId: string) => Route;
}

function tenantRow(
  tenant: Tenant,
  { hrefFor, impersonateHref }: Omit<AdminTenantsViewProps, "tenants">,
): TenantRow {
  return {
    id: tenant.id,
    name: tenant.name,
    href: hrefFor === undefined ? null : hrefFor(tenant.id),
    kind: tenant.kind,
    kindLabel: tenantKindLabel(tenant.kind),
    status: tenant.status,
    statusLabel: tenantStatusLabel(tenant.status),
    statusTone: tenantStatusTone(tenant.status),
    region: tenant.region,
    created: formatDate(tenant.createdAt),
    impersonateHref:
      impersonateHref !== undefined && canImpersonate(tenant) ? impersonateHref(tenant.id) : null,
  };
}

/**
 * The tenants console: how many tenants there are and how many are active, awaiting deletion or
 * erased, then every tenant by name under kind tabs with a search, or an empty state before the
 * first sign-up.
 */
export function AdminTenantsView({ tenants, ...links }: AdminTenantsViewProps) {
  const summary = tenantsSummary(tenants);
  return (
    <div data-slot="admin-tenants" className="flex flex-col gap-6">
      <PageHeader title={t("adminTenants.title")} description={t("adminTenants.description")} />
      {tenants.length === 0 ? (
        <EmptyState
          title={t("adminTenants.noTenants.title")}
          body={t("adminTenants.noTenants.body")}
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("adminTenants.stat.total")} value={summary.total} tone="info" />
            <StatCard label={t("adminTenants.stat.active")} value={summary.active} tone="success" />
            <StatCard
              label={t("adminTenants.stat.deletionRequested")}
              value={summary.deletionRequested}
              tone={summary.deletionRequested > 0 ? "warning" : "neutral"}
            />
            <StatCard label={t("adminTenants.stat.erased")} value={summary.erased} />
          </div>
          <TenantsTable
            rows={sortTenants(tenants).map((tenant) => tenantRow(tenant, links))}
            kindTabs={tenantKindTabs()}
          />
        </>
      )}
    </div>
  );
}
