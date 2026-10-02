"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  Icon,
  PageHeader,
  SearchInput,
  Select,
  StatCard,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  EmptyState,
} from "@compliancewatch/ui";
import type { ReportView } from "../model/reports";
import { reportFormatLabel, reportStatusLabel } from "../model/reports";

export interface ReportViewProps {
  view: ReportView;
}

const FORMATS = [
  { value: "all", label: "All formats" },
  { value: "pdf", label: "PDF" },
  { value: "xlsx", label: "Excel" },
  { value: "csv", label: "CSV" },
];

const STATUSES = [
  { value: "all", label: "All statuses" },
  { value: "ready", label: "Ready" },
  { value: "generating", label: "Generating" },
  { value: "failed", label: "Failed" },
];

/** The reports page for owners and CA firms. */
export function ReportViewComponent({ view }: ReportViewProps) {
  const [search, setSearch] = useState("");
  const [formatFilter, setFormatFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const filtered = view.reports.filter((report) => {
    if (search && !report.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (formatFilter !== "all" && report.format !== formatFilter) return false;
    if (statusFilter !== "all" && report.status !== statusFilter) return false;
    return true;
  });

  return (
    <div data-slot="reports" className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader title="Reports" description="Generate and download compliance reports" />
        <Button>
          <Icon name="plus" className="mr-2 h-4 w-4" />
          Generate report
        </Button>
      </div>

      {view.totalCount === 0 ? (
        <Card>
          <EmptyState
            icon={<Icon name="file-text" className="h-8 w-8 text-fg-muted" />}
            title="No reports yet"
            description="Generate your first compliance report to see it here."
          />
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card className="p-4">
              <div className="text-sm text-fg-muted">Total reports</div>
              <div className="text-2xl font-bold text-fg">{view.totalCount}</div>
            </Card>
            <Card className="p-4">
              <div className="text-sm text-fg-muted">Ready</div>
              <div className="text-2xl font-bold text-success">
                {view.reports.filter((r) => r.status === "ready").length}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-sm text-fg-muted">Generating</div>
              <div className="text-2xl font-bold text-warning">
                {view.reports.filter((r) => r.status === "generating").length}
              </div>
            </Card>
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-3 sm:flex-row">
              <SearchInput
                placeholder="Search reports..."
                value={search}
                onChange={setSearch}
                className="flex-1"
              />
              <Select
                value={formatFilter}
                onChange={setFormatFilter}
                options={FORMATS}
                className="w-full sm:w-40"
              />
              <Select
                value={statusFilter}
                onChange={setStatusFilter}
                options={STATUSES}
                className="w-full sm:w-40"
              />
            </div>

            {filtered.length === 0 ? (
              <Card>
                <EmptyState title="No reports match" description="Try adjusting your filters." />
              </Card>
            ) : (
              <div className="overflow-hidden rounded-md border border-line">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Format</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Generated</TableHead>
                      <TableHead>Size</TableHead>
                      <TableHead>Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtered.map((report) => (
                      <TableRow key={report.id}>
                        <TableCell className="font-medium text-fg">{report.name}</TableCell>
                        <TableCell>{reportFormatLabel(report.format)}</TableCell>
                        <TableCell>
                          <Badge
                            tone={
                              report.status === "ready"
                                ? "success"
                                : report.status === "generating"
                                  ? "warning"
                                  : "danger"
                            }
                          >
                            {reportStatusLabel(report.status)}
                          </Badge>
                        </TableCell>
                        <TableCell>{new Date(report.generatedAt).toLocaleDateString()}</TableCell>
                        <TableCell>{report.size}</TableCell>
                        <TableCell>
                          {report.url && report.status === "ready" ? (
                            <Button variant="ghost" size="sm" asChild>
                              <a href={report.url} download>
                                Download
                              </a>
                            </Button>
                          ) : (
                            <span className="text-sm text-fg-muted">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
