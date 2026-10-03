"use client";

import Link from "next/link";
import { useId, useState } from "react";
import {
  Button,
  EmptyState,
  Field,
  Input,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  VisuallyHidden,
  type SelectOption,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ALL, NO_TENANT_FILTERS, filterTenants, type TenantRow } from "./tenant-filters";

export interface TenantsTableProps {
  rows: readonly TenantRow[];
  /** One tab per tenant kind; an "All" tab comes first. */
  kindTabs: readonly SelectOption[];
}

function TenantTable({ rows, actions }: { rows: readonly TenantRow[]; actions: boolean }) {
  return (
    <Table>
      <TableCaption className="sr-only">{t("adminTenants.title")}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("adminTenants.column.name")}</TableHead>
          <TableHead>{t("adminTenants.column.kind")}</TableHead>
          <TableHead>{t("adminTenants.column.status")}</TableHead>
          <TableHead>{t("adminTenants.column.region")}</TableHead>
          <TableHead>{t("adminTenants.column.created")}</TableHead>
          {actions ? <TableHead>{t("adminTenants.column.actions")}</TableHead> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-tenant={row.id}>
            <TableCell className="font-medium text-fg">
              {row.href === null ? (
                row.name
              ) : (
                <Link href={row.href} className="underline-offset-4 hover:underline">
                  {row.name}
                </Link>
              )}
            </TableCell>
            <TableCell>{row.kindLabel}</TableCell>
            <TableCell>
              <StatusChip status={row.status} tone={row.statusTone} label={row.statusLabel} />
            </TableCell>
            <TableCell className="font-mono text-xs">{row.region}</TableCell>
            <TableCell className="text-fg-muted">{row.created}</TableCell>
            {actions ? (
              <TableCell>
                {row.impersonateHref === null ? null : (
                  <Button asChild variant="secondary" size="sm">
                    <Link href={row.impersonateHref}>
                      {t("adminTenants.action.impersonate")}
                      <VisuallyHidden> {row.name}</VisuallyHidden>
                    </Link>
                  </Button>
                )}
              </TableCell>
            ) : null}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The tenants under kind tabs, narrowed in the browser by a search over the name and the id.
 * The actions column appears only when some tenant can be impersonated.
 */
export function TenantsTable({ rows, kindTabs }: TenantsTableProps) {
  const id = useId();
  const [filters, setFilters] = useState(NO_TENANT_FILTERS);
  const shown = filterTenants(rows, filters);
  const tabs = [{ value: ALL, label: t("adminTenants.filter.all") }, ...kindTabs];
  const actions = rows.some((row) => row.impersonateHref !== null);

  return (
    <div data-slot="tenants-table" className="flex flex-col gap-4">
      <Field id={`${id}-search`} label={t("adminTenants.filter.search")} className="sm:max-w-sm">
        <Input
          type="search"
          value={filters.search}
          onChange={(event) => setFilters({ ...filters, search: event.target.value })}
        />
      </Field>
      <Tabs value={filters.kind} onValueChange={(kind) => setFilters({ ...filters, kind })}>
        <TabsList aria-label={t("adminTenants.filter.label")}>
          {tabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <p role="status" className="text-sm text-fg-muted">
          {t("adminTenants.caption", { shown: shown.length, total: rows.length })}
        </p>
        {tabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            {shown.length === 0 ? (
              <EmptyState
                title={t("adminTenants.emptyTitle")}
                body={t("adminTenants.emptyBody")}
                action={
                  <Button variant="secondary" onClick={() => setFilters(NO_TENANT_FILTERS)}>
                    {t("adminTenants.clearFilters")}
                  </Button>
                }
              />
            ) : (
              <TenantTable rows={shown} actions={actions} />
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
