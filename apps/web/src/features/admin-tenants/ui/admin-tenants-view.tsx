"use client";

import { useMemo } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  PageHeader,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
} from "@compliancewatch/ui";
import {
  tenantKindLabel,
  tenantStatusLabel,
  tenantStatusTone,
} from "../model/admin-tenants";
import type { AdminTenantsView, Tenant } from "../model/admin-tenants";

export interface AdminTenantsViewProps {
  view: AdminTenantsView;
  onImpersonate?: (tenantId: string) => void;
}

function TenantRow({ tenant, onImpersonate }: { tenant: Tenant; onImpersonate?: (id: string) => void }) {
  return (
    <TableRow>
      <TableCell>
        <span className="font-medium text-fg">{tenant.name}</span>
      </TableCell>
      <TableCell>
        <Badge tone="info">{tenantKindLabel(tenant.kind)}</Badge>
      </TableCell>
      <TableCell>
        <Badge tone={tenantStatusTone(tenant.status)}>{tenantStatusLabel(tenant.status)}</Badge>
      </TableCell>
      <TableCell className="text-fg-muted">{tenant.memberCount}</TableCell>
      <TableCell>
        <div className="flex items-center gap-2">
          <div className="h-2 w-16 rounded-full bg-muted">
            <div
              className="h-2 rounded-full bg-success"
              style={{ width: `${tenant.complianceScore}%` }}
            />
          </div>
          <span className="text-xs text-fg-muted">{tenant.complianceScore}%</span>
        </div>
      </TableCell>
      <TableCell className="text-fg-muted">
        {new Date(tenant.createdAt).toLocaleDateString()}
      </TableCell>
      <TableCell>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm">View</Button>
          <Button variant="ghost" size="sm" onClick={() => onImpersonate?.(tenant.id)}>
            Impersonate
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

export function AdminTenantsViewComponent({ view, onImpersonate }: AdminTenantsViewProps) {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<AdminTenantsView["filter"]>(view.filter);

  const filtered = useMemo(() => {
    let items = view.tenants;
    if (tab !== "all") {
      items = items.filter((t) => t.kind === tab);
    }
    if (search) {
      const q = search.toLowerCase();
      items = items.filter((t) => t.name.toLowerCase().includes(q));
    }
    return items;
  }, [view.tenants, tab, search]);

  const activeCount = view.tenants.filter((t) => t.status === "active").length;
  const suspendedCount = view.tenants.filter((t) => t.status === "suspended").length;

  return (
    <div data-slot="admin-tenants" className="flex flex-col gap-6">
      <PageHeader title="Tenants" description="Manage business and CA firm tenants" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total tenants</p>
          <p className="text-2xl font-semibold text-fg">{view.totalCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Active</p>
          <p className="text-2xl font-semibold text-success">{activeCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Suspended</p>
          <p className="text-2xl font-semibold text-danger">{suspendedCount}</p>
        </Card>
      </div>

      <Tabs
        tabs={[
          { value: "all", label: "All tenants" },
          { value: "business", label: "Business" },
          { value: "ca_firm", label: "CA firm" },
        ]}
        value={tab}
        onChange={(v) => setTab(v as AdminTenantsView["filter"])}
      />

      <Input
        placeholder="Search tenants..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {filtered.length === 0 ? (
        <Card>
          <EmptyState
            title="No tenants found"
            description="Tenants will appear here once registered."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Members</TableHead>
                <TableHead>Compliance</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((tenant) => (
                <TenantRow key={tenant.id} tenant={tenant} onImpersonate={onImpersonate} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}