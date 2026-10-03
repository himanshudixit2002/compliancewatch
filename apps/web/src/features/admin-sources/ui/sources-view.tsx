"use client";

import { useMemo } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { dataSourceStatusTone } from "../model/sources";
import type { AdminSourcesView } from "../model/sources";

export interface AdminSourcesViewProps {
  view: AdminSourcesView;
}

function SourceRow({ source }: { source: AdminSourcesView["sources"][number] }) {
  return (
    <TableRow>
      <TableCell className="font-medium text-fg">{source.name}</TableCell>
      <TableCell>
        <Badge tone="info">{source.type}</Badge>
      </TableCell>
      <TableCell>
        <Badge tone={dataSourceStatusTone(source.status)}>{source.status}</Badge>
      </TableCell>
      <TableCell className="text-fg-muted">{source.lastSync ? new Date(source.lastSync).toLocaleString() : "Never"}</TableCell>
      <TableCell className="text-fg-muted">{source.recordCount.toLocaleString()}</TableCell>
      <TableCell>
        <Button variant="ghost" size="sm">Sync</Button>
      </TableCell>
    </TableRow>
  );
}

export function AdminSourcesViewComponent({ view }: AdminSourcesViewProps) {
  const connectedCount = useMemo(() => view.sources.filter((s) => s.status === "connected").length, [view.sources]);

  return (
    <div data-slot="admin-sources" className="flex flex-col gap-6">
      <PageHeader title="Data sources" description="Manage external data sources and integrations" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total sources</p>
          <p className="text-2xl font-semibold text-fg">{view.totalCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Connected</p>
          <p className="text-2xl font-semibold text-success">{connectedCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Errors</p>
          <p className="text-2xl font-semibold text-danger">{view.sources.filter((s) => s.status === "error").length}</p>
        </Card>
      </div>

      {view.sources.length === 0 ? (
        <Card>
          <EmptyState
            title="No data sources"
            description="Connect external data sources to enrich compliance data."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last sync</TableHead>
                <TableHead>Records</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.sources.map((source) => (
                <SourceRow key={source.id} source={source} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}