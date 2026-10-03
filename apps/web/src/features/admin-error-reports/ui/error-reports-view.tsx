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
} from "@compliancewatch/ui";
import { errorSeverityTone } from "../model/error-reports";
import type { AdminErrorReportsView } from "../model/error-reports";

export interface AdminErrorReportsViewProps {
  view: AdminErrorReportsView;
}

function ErrorReportRow({ report }: { report: AdminErrorReportsView["reports"][number] }) {
  return (
    <TableRow>
      <TableCell className="font-medium text-fg">{report.title}</TableCell>
      <TableCell>
        <Badge tone={errorSeverityTone(report.severity)}>{report.severity}</Badge>
      </TableCell>
      <TableCell>
        <Badge tone="info">{report.status}</Badge>
      </TableCell>
      <TableCell className="text-fg-muted">{report.source}</TableCell>
      <TableCell className="text-fg-muted max-w-xs truncate">{report.message}</TableCell>
      <TableCell className="text-fg-muted">{new Date(report.createdAt).toLocaleString()}</TableCell>
      <TableCell>
        <Button variant="ghost" size="sm">View</Button>
      </TableCell>
    </TableRow>
  );
}

export function AdminErrorReportsViewComponent({ view }: AdminErrorReportsViewProps) {
  const criticalCount = useMemo(() => view.reports.filter((r) => r.severity === "critical" || r.severity === "high").length, [view.reports]);

  return (
    <div data-slot="admin-error-reports" className="flex flex-col gap-6">
      <PageHeader title="Error reports" description="Track and resolve system errors" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total errors</p>
          <p className="text-2xl font-semibold text-fg">{view.totalCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Critical/High</p>
          <p className="text-2xl font-semibold text-danger">{criticalCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Resolved</p>
          <p className="text-2xl font-semibold text-success">{view.reports.filter((r) => r.resolvedAt).length}</p>
        </Card>
      </div>

      <Input
        placeholder="Search errors..."
        onChange={() => {}}
      />

      {view.reports.length === 0 ? (
        <Card>
          <EmptyState
            title="No error reports"
            description="System errors will appear here."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.reports.map((report) => (
                <ErrorReportRow key={report.id} report={report} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}